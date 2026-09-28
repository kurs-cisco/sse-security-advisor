import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cr from "aws-cdk-lib/custom-resources";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as rds from "aws-cdk-lib/aws-rds";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as route53Targets from "aws-cdk-lib/aws-route53-targets";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";
import { OIDC_PRODUCT_SCOPES, OIDC_SERVICE_GROUPS } from "./oidc-service-groups";

function asBoolean(value: unknown): boolean {
  return value === true || value === "true";
}

function requiredContext(scope: Construct, key: string): string {
  const value = scope.node.tryGetContext(key);
  if (value === undefined || value === null || String(value).trim() === "") {
    throw new Error(`Missing required CDK context: ${key}`);
  }
  return String(value);
}

function oidcGroupScopeJson(scope: Construct): string {
  const policy = scope.node.tryGetContext("oidcGroupScope");
  if (!policy || typeof policy !== "object" || Array.isArray(policy)) {
    throw new Error("Missing oidcGroupScope deployment policy");
  }
  const version = (policy as { version?: unknown }).version;
  if (typeof version !== "string" || !version.trim()) {
    throw new Error("oidcGroupScope must have a version");
  }
  const groups = (policy as { groups?: unknown }).groups;
  if (!groups || typeof groups !== "object" || Array.isArray(groups)) {
    throw new Error("oidcGroupScope must contain exact group mappings");
  }
  const entries: Record<string, { access?: unknown; grants?: unknown; service_key?: unknown }> = {
    ...groups as Record<string, { access?: unknown; grants?: unknown; service_key?: unknown }>,
  };
  const productScopesById = new Map<string, (typeof OIDC_PRODUCT_SCOPES)[number]>();
  for (const productScope of OIDC_PRODUCT_SCOPES) {
    if (productScopesById.has(productScope.product_scope_id)) {
      throw new Error(`Duplicate product scope policy identity: ${productScope.product_scope_id}`);
    }
    productScopesById.set(productScope.product_scope_id, productScope);
  }
  if (asBoolean(scope.node.tryGetContext("enableOidcServiceGroups"))) {
    const globalGroups = new Set(["fedsse-admins", "fedsse-external", "fedsse-scr2-leads"]);
    if (Object.keys(entries).some((name) => !globalGroups.has(name))) {
      throw new Error("Enabled service grants must come only from the exact OIDC service registry");
    }
    const seenServices = new Set<string>();
    for (const service of OIDC_SERVICE_GROUPS) {
      const pair = `${service.source_collection}\u0000${service.service_group}`;
      if (seenServices.has(pair)) throw new Error(`Duplicate OIDC service identity: ${pair}`);
      seenServices.add(pair);
      for (const [suffix, access] of [["leads", "lead"], ["engineers", "engineer"]] as const) {
        const name = `fedsse-${service.service_key}-${suffix}`;
        if (entries[name] !== undefined) throw new Error(`Duplicate OIDC access group: ${name}`);
        entries[name] = {
          access,
          service_key: service.service_key,
          grants: OIDC_PRODUCT_SCOPES.map((productScope) => ({
            source_collection: service.source_collection,
            service_group: service.service_group,
            product_scope_id: productScope.product_scope_id,
            boundary_name: productScope.boundary_name,
          })),
        };
      }
    }
  }
  if (entries["fedsse-admins"]?.access !== "admin"
    || entries["fedsse-external"]?.access !== "summary"
    || entries["fedsse-scr2-leads"]?.access !== "summary") {
    throw new Error("oidcGroupScope must define the approved administrator and summary groups");
  }
  for (const [name, entry] of Object.entries(entries)) {
    if (!/^fedsse-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)
      || !entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`Invalid OIDC access group: ${name}`);
    }
    if (name === "fedsse-admins" || name === "fedsse-external" || name === "fedsse-scr2-leads") {
      if (entry.grants !== undefined) throw new Error(`Global group cannot carry service grants: ${name}`);
      continue;
    }
    if ((entry.access !== "lead" && entry.access !== "engineer")
      || !name.endsWith(entry.access === "lead" ? "-leads" : "-engineers")
      || !Array.isArray(entry.grants) || entry.grants.length === 0) {
      throw new Error(`Service group requires explicit lead/engineer grants: ${name}`);
    }
    const serviceKey = (entry as { service_key?: unknown }).service_key;
    const suffix = entry.access === "lead" ? "leads" : "engineers";
    if (typeof serviceKey !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(serviceKey)
      || name !== `fedsse-${serviceKey}-${suffix}`) {
      throw new Error(`Service group key must exactly match the OIDC group stem: ${name}`);
    }
    const triples = new Set<string>();
    for (const grant of entry.grants) {
      if (!grant || typeof grant !== "object" || Array.isArray(grant)) {
        throw new Error(`Invalid service grant for ${name}`);
      }
      const fields = grant as Record<string, unknown>;
      for (const field of ["source_collection", "service_group", "product_scope_id", "boundary_name"]) {
        const value = fields[field];
        if (typeof value !== "string" || !value.trim() || value !== value.trim()
          || /[<>]/.test(value) || value.toLowerCase() === "tbd") {
          throw new Error(`Invalid ${field} in service grant for ${name}`);
        }
      }
      const triple = `${fields.source_collection}\u0000${fields.service_group}\u0000${fields.product_scope_id}`;
      if (triples.has(triple)) throw new Error(`Duplicate collection/service/product grant for ${name}`);
      triples.add(triple);
      const productScope = productScopesById.get(String(fields.product_scope_id));
      if (!productScope || fields.boundary_name !== productScope.boundary_name) {
        throw new Error(`Service grant must use an exact approved product scope and boundary name for ${name}`);
      }
    }
  }
  return JSON.stringify({ ...policy, product_scopes: OIDC_PRODUCT_SCOPES, groups: entries });
}

export class CbomWorkbenchStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    const vpcId = requiredContext(this, "vpcId");
    const zoneId = requiredContext(this, "hostedZoneId");
    const zoneName = requiredContext(this, "hostedZoneName");
    const hostname = requiredContext(this, "hostname");
    const apiHostname = requiredContext(this, "apiHostname");
    const imageTag = requiredContext(this, "imageTag");
    const availabilityZones = this.node.tryGetContext("availabilityZones") as string[];
    const publicSubnetIds = this.node.tryGetContext("publicSubnetIds") as string[];
    const publicSubnetRouteTableIds = this.node.tryGetContext("publicSubnetRouteTableIds") as string[];
    const privateSubnetIds = this.node.tryGetContext("privateSubnetIds") as string[];
    const privateSubnetRouteTableIds = this.node.tryGetContext("privateSubnetRouteTableIds") as string[];
    const activateServices = asBoolean(this.node.tryGetContext("activateServices"));
    const enableOidc = asBoolean(this.node.tryGetContext("enableOidc"));
    const enableOidcServiceGroups = asBoolean(this.node.tryGetContext("enableOidcServiceGroups"));
    const enableAdminGroupMapping = asBoolean(this.node.tryGetContext("enableAdminGroupMapping"));
    const enableProductScopedDetailEvidence = asBoolean(this.node.tryGetContext("enableProductScopedDetailEvidence"));
    const enableAccessRoster = asBoolean(this.node.tryGetContext("enableAccessRoster"));
    const enableLeadReviewProposals = asBoolean(this.node.tryGetContext("enableLeadReviewProposals"));
    const enableOperationalEvidenceNotes = asBoolean(this.node.tryGetContext("enableOperationalEvidenceNotes"));
    const enableServiceCatalog = asBoolean(this.node.tryGetContext("enableServiceCatalog"));
    if (enableProductScopedDetailEvidence && !enableOidcServiceGroups) {
      throw new Error("Product detail requires exact OIDC service-group grants");
    }
    if (enableAdminGroupMapping && !enableOidcServiceGroups) {
      throw new Error("Administrator group mapping requires exact OIDC service-group grants");
    }
    if (enableOperationalEvidenceNotes && !enableProductScopedDetailEvidence) {
      throw new Error("Operational evidence notes require product-scoped detail");
    }
    if (enableLeadReviewProposals && !enableProductScopedDetailEvidence) {
      throw new Error("Lead review proposals require product-scoped detail");
    }
    if (enableServiceCatalog && !enableOidcServiceGroups) {
      throw new Error("Service Catalog requires exact OIDC service-group grants");
    }
    const groupScopeJson = oidcGroupScopeJson(this);
    const reuseRetainedBootstrapResources = asBoolean(
      this.node.tryGetContext("reuseRetainedBootstrapResources"),
    );

    if (availabilityZones.length !== publicSubnetIds.length || availabilityZones.length !== privateSubnetIds.length) {
      throw new Error("Each availability zone must have one configured public and private subnet");
    }

    const vpc = ec2.Vpc.fromVpcAttributes(this, "Vpc", {
      vpcId,
      availabilityZones,
      publicSubnetIds,
      publicSubnetRouteTableIds,
      privateSubnetIds,
      privateSubnetRouteTableIds,
    });
    const publicSubnets = publicSubnetIds.map((subnetId, index) =>
      ec2.Subnet.fromSubnetAttributes(this, `PublicSubnet${index + 1}`, {
        subnetId,
        availabilityZone: availabilityZones[index],
        routeTableId: publicSubnetRouteTableIds[index],
      }),
    );
    const privateSubnets = privateSubnetIds.map((subnetId, index) =>
      ec2.Subnet.fromSubnetAttributes(this, `PrivateSubnet${index + 1}`, {
        subnetId,
        availabilityZone: availabilityZones[index],
        routeTableId: privateSubnetRouteTableIds[index],
      }),
    );

    const zone = route53.HostedZone.fromHostedZoneAttributes(this, "HostedZone", {
      hostedZoneId: zoneId,
      zoneName,
    });

    const webRepository: ecr.IRepository = reuseRetainedBootstrapResources
      ? ecr.Repository.fromRepositoryName(this, "WebRepository", "cbom-workbench/web")
      : new ecr.Repository(this, "WebRepository", {
          repositoryName: "cbom-workbench/web",
          imageScanOnPush: true,
          imageTagMutability: ecr.TagMutability.IMMUTABLE,
          encryption: ecr.RepositoryEncryption.AES_256,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
          lifecycleRules: [{ maxImageCount: 20, description: "Retain the 20 newest web images" }],
        });
    const catalogRepository: ecr.IRepository = reuseRetainedBootstrapResources
      ? ecr.Repository.fromRepositoryName(this, "CatalogRepository", "cbom-workbench/catalog")
      : new ecr.Repository(this, "CatalogRepository", {
          repositoryName: "cbom-workbench/catalog",
          imageScanOnPush: true,
          imageTagMutability: ecr.TagMutability.IMMUTABLE,
          encryption: ecr.RepositoryEncryption.AES_256,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
          lifecycleRules: [{ maxImageCount: 20, description: "Retain the 20 newest catalog images" }],
        });

    const dataBucketName = `cbom-workbench-data-${this.account}-${this.region}`;
    const dataBucket: s3.IBucket = reuseRetainedBootstrapResources
      ? s3.Bucket.fromBucketName(this, "DataBucket", dataBucketName)
      : new s3.Bucket(this, "DataBucket", {
          bucketName: dataBucketName,
          blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
          enforceSSL: true,
          encryption: s3.BucketEncryption.KMS_MANAGED,
          versioned: true,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
          lifecycleRules: [{
            id: "expire-temporary-transfer-files",
            prefix: "transfer/",
            expiration: cdk.Duration.days(14),
            noncurrentVersionExpiration: cdk.Duration.days(14),
          }],
        });

    const ingestionCorsCall: cr.AwsSdkCall = {
      service: "S3",
      action: "putBucketCors",
      parameters: {
        Bucket: dataBucket.bucketName,
        CORSConfiguration: {
          CORSRules: [{
            AllowedHeaders: ["content-type", "x-amz-checksum-sha256"],
            AllowedMethods: ["PUT"],
            AllowedOrigins: [`https://${hostname}`],
            ExposeHeaders: ["ETag", "x-amz-checksum-sha256"],
            MaxAgeSeconds: 3600,
          }],
        },
      },
      physicalResourceId: cr.PhysicalResourceId.of(`${dataBucketName}-ingestion-cors-${hostname}`),
    };
    new cr.AwsCustomResource(this, "IngestionUploadCors", {
      onCreate: ingestionCorsCall,
      onUpdate: ingestionCorsCall,
      installLatestAwsSdk: false,
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ["s3:PutBucketCORS"],
          resources: [dataBucket.bucketArn],
        }),
      ]),
    });

    const oidcSecret: secretsmanager.ISecret = reuseRetainedBootstrapResources
      ? secretsmanager.Secret.fromSecretCompleteArn(
          this,
          "OidcClientSecret",
          requiredContext(this, "oidcSecretArn"),
        )
      : new secretsmanager.Secret(this, "OidcClientSecret", {
          secretName: "/cbom-workbench/dev/oidc-client-secret",
          description: "Populate with the rotated CBOM OIDC client secret before enabling DNS",
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });
    const apiBearerSecret: secretsmanager.ISecret = reuseRetainedBootstrapResources
      ? secretsmanager.Secret.fromSecretCompleteArn(
          this,
          "ApiBearerSecret",
          requiredContext(this, "apiBearerSecretArn"),
        )
      : new secretsmanager.Secret(this, "ApiBearerSecret", {
          secretName: "/cbom-workbench/dev/api-bearer-token",
          description: "Internal bearer token shared only by Next.js and FastAPI",
          generateSecretString: { excludePunctuation: true, passwordLength: 64 },
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });
    const apiTokenPepper: secretsmanager.ISecret = reuseRetainedBootstrapResources
      ? secretsmanager.Secret.fromSecretCompleteArn(
          this,
          "ApiTokenPepper",
          requiredContext(this, "apiTokenPepperArn"),
        )
      : new secretsmanager.Secret(this, "ApiTokenPepper", {
          secretName: "/cbom-workbench/dev/api-token-pepper",
          description: "HMAC pepper for one-time CBOM application API credentials",
          generateSecretString: { excludePunctuation: true, passwordLength: 64 },
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const albSecurityGroup = new ec2.SecurityGroup(this, "AlbSecurityGroup", {
      vpc,
      allowAllOutbound: false,
      description: "Public HTTPS ingress for CBOM Workbench",
    });
    albSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), "Public HTTPS");
    albSecurityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), "HTTP redirect only");
    albSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      "OIDC authorization, token, and user-info endpoints",
    );

    const webSecurityGroup = new ec2.SecurityGroup(this, "WebSecurityGroup", {
      vpc,
      allowAllOutbound: true,
      description: "CBOM Next.js workload",
    });
    webSecurityGroup.addIngressRule(albSecurityGroup, ec2.Port.tcp(3000), "Only the ALB may reach Next.js");
    webSecurityGroup.addIngressRule(albSecurityGroup, ec2.Port.tcp(8000), "Only the ALB may reach the token API");

    const jobSecurityGroup = new ec2.SecurityGroup(this, "JobSecurityGroup", {
      vpc,
      allowAllOutbound: true,
      description: "CBOM migration, restore, and ingestion jobs",
    });

    const databaseSecurityGroup = new ec2.SecurityGroup(this, "DatabaseSecurityGroup", {
      vpc,
      allowAllOutbound: false,
      description: "CBOM PostgreSQL ingress",
    });
    databaseSecurityGroup.addIngressRule(webSecurityGroup, ec2.Port.tcp(5432), "Application task to PostgreSQL");
    databaseSecurityGroup.addIngressRule(jobSecurityGroup, ec2.Port.tcp(5432), "Jobs to PostgreSQL");

    const database = new rds.DatabaseInstance(this, "Database", {
      instanceIdentifier: "cbom-workbench-dev",
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.of("16.15", "16"),
      }),
      instanceType: new ec2.InstanceType("t4g.small"),
      credentials: rds.Credentials.fromGeneratedSecret("cbom_admin", {
        secretName: "/cbom-workbench/dev/database",
        excludeCharacters: " @%+~`#$&*()|[]{}:;'\"<>?!/\\",
      }),
      databaseName: "cbom_catalog",
      allocatedStorage: 30,
      maxAllocatedStorage: 200,
      storageEncrypted: true,
      multiAz: false,
      publiclyAccessible: false,
      deletionProtection: true,
      backupRetention: cdk.Duration.days(7),
      deleteAutomatedBackups: false,
      copyTagsToSnapshot: true,
      vpc,
      vpcSubnets: { subnets: privateSubnets },
      securityGroups: [databaseSecurityGroup],
      cloudwatchLogsExports: ["postgresql"],
      cloudwatchLogsRetention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
    });

    const cluster = new ecs.Cluster(this, "Cluster", {
      clusterName: "cbom-workbench-dev",
      vpc,
      containerInsightsV2: ecs.ContainerInsights.ENABLED,
    });
    const webLogGroup: logs.ILogGroup = reuseRetainedBootstrapResources
      ? logs.LogGroup.fromLogGroupName(this, "WebLogGroup", "/cbom-workbench/dev/web")
      : new logs.LogGroup(this, "WebLogGroup", {
          logGroupName: "/cbom-workbench/dev/web",
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });
    const apiLogGroup: logs.ILogGroup = reuseRetainedBootstrapResources
      ? logs.LogGroup.fromLogGroupName(this, "ApiLogGroup", "/cbom-workbench/dev/api")
      : new logs.LogGroup(this, "ApiLogGroup", {
          logGroupName: "/cbom-workbench/dev/api",
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });
    const jobLogGroup: logs.ILogGroup = reuseRetainedBootstrapResources
      ? logs.LogGroup.fromLogGroupName(this, "JobLogGroup", "/cbom-workbench/dev/jobs")
      : new logs.LogGroup(this, "JobLogGroup", {
          logGroupName: "/cbom-workbench/dev/jobs",
          retention: logs.RetentionDays.ONE_MONTH,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
        });

    const databaseSecret = database.secret;
    if (!databaseSecret) throw new Error("RDS failed to provide its generated credential secret");
    databaseSecret.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);

    const webTask = new ecs.FargateTaskDefinition(this, "WebTask", {
      family: "cbom-workbench-web",
      cpu: 1024,
      memoryLimitMiB: 3072,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    const apiContainer = webTask.addContainer("api", {
      image: ecs.ContainerImage.fromEcrRepository(catalogRepository, imageTag),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "api",
        logGroup: apiLogGroup,
        mode: ecs.AwsLogDriverMode.BLOCKING,
      }),
      environment: {
        PGHOST: database.instanceEndpoint.hostname,
        PGPORT: database.instanceEndpoint.port.toString(),
        PGDATABASE: "cbom_catalog",
        CBOM_ENVIRONMENT: "production",
        CBOM_API_AUTH_MODE: "bearer",
        CBOM_API_ALLOW_RAW: "false",
        CBOM_API_PAGE_SIZE: "100",
        CBOM_API_POOL_MIN_SIZE: "2",
        CBOM_API_POOL_MAX_SIZE: "8",
        CBOM_API_STATEMENT_TIMEOUT_MS: "20000",
        CBOM_API_PREWARM: "true",
        CBOM_ASSESSMENT_TIMEZONE: "Asia/Kolkata",
        CBOM_OIDC_ISSUER: requiredContext(this, "oidcIssuer"),
        CBOM_OIDC_GROUP_SCOPE_JSON: groupScopeJson,
        CBOM_ADMIN_GROUP_MAPPING_ENABLED: enableAdminGroupMapping ? "true" : "false",
        CBOM_PRODUCT_SCOPED_DETAIL_EVIDENCE_ENABLED: enableProductScopedDetailEvidence ? "true" : "false",
        CBOM_ACCESS_ROSTER_ENABLED: enableAccessRoster ? "true" : "false",
        CBOM_LEAD_REVIEW_PROPOSALS_ENABLED: enableLeadReviewProposals ? "true" : "false",
        CBOM_OPERATIONAL_EVIDENCE_NOTES_ENABLED: enableOperationalEvidenceNotes ? "true" : "false",
        CBOM_SERVICE_CATALOG_ENABLED: enableServiceCatalog ? "true" : "false",
      },
      secrets: {
        PGUSER: ecs.Secret.fromSecretsManager(databaseSecret, "username"),
        PGPASSWORD: ecs.Secret.fromSecretsManager(databaseSecret, "password"),
        CBOM_API_BEARER_TOKEN: ecs.Secret.fromSecretsManager(apiBearerSecret),
        CBOM_API_TOKEN_PEPPER: ecs.Secret.fromSecretsManager(apiTokenPepper),
      },
      healthCheck: {
        command: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)\" || exit 1"],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(30),
      },
    });
    apiContainer.addPortMappings({ containerPort: 8000, protocol: ecs.Protocol.TCP });

    const accessLogBucketName = `cbom-workbench-access-logs-${this.account}-${this.region}`;
    const accessLogBucket: s3.IBucket = reuseRetainedBootstrapResources
      ? s3.Bucket.fromBucketName(this, "AccessLogBucket", accessLogBucketName)
      : new s3.Bucket(this, "AccessLogBucket", {
          bucketName: accessLogBucketName,
          blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
          enforceSSL: true,
          encryption: s3.BucketEncryption.S3_MANAGED,
          versioned: false,
          removalPolicy: cdk.RemovalPolicy.RETAIN,
          lifecycleRules: [{ id: "expire-access-logs", expiration: cdk.Duration.days(90) }],
        });

    new s3.CfnBucketPolicy(this, "AccessLogBucketPolicy", {
      bucket: accessLogBucket.bucketName,
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "AllowLogDeliveryAclCheck",
            Effect: "Allow",
            Principal: { Service: "delivery.logs.amazonaws.com" },
            Action: "s3:GetBucketAcl",
            Resource: accessLogBucket.bucketArn,
          },
          {
            Sid: "AllowAlbLogDelivery",
            Effect: "Allow",
            Principal: {
              AWS: `arn:${cdk.Aws.PARTITION}:iam::190560391635:root`,
              Service: "delivery.logs.amazonaws.com",
            },
            Action: "s3:PutObject",
            Resource: `${accessLogBucket.bucketArn}/alb/AWSLogs/${this.account}/*`,
          },
          {
            Sid: "DenyInsecureTransport",
            Effect: "Deny",
            Principal: "*",
            Action: "s3:*",
            Resource: [accessLogBucket.bucketArn, `${accessLogBucket.bucketArn}/*`],
            Condition: { Bool: { "aws:SecureTransport": "false" } },
          },
        ],
      },
    });

    const loadBalancer = new elbv2.ApplicationLoadBalancer(this, "LoadBalancer", {
      loadBalancerName: "cbom-workbench-dev",
      vpc,
      internetFacing: true,
      securityGroup: albSecurityGroup,
      vpcSubnets: { subnets: publicSubnets },
      dropInvalidHeaderFields: true,
      deletionProtection: true,
    });
    loadBalancer.setAttribute("access_logs.s3.enabled", "true");
    loadBalancer.setAttribute("access_logs.s3.bucket", accessLogBucket.bucketName);
    loadBalancer.setAttribute("access_logs.s3.prefix", "alb");

    const certificate = new acm.Certificate(this, "Certificate", {
      domainName: hostname,
      validation: acm.CertificateValidation.fromDns(zone),
    });
    const apiCertificate = new acm.Certificate(this, "ApiCertificate", {
      domainName: apiHostname,
      validation: acm.CertificateValidation.fromDns(zone),
    });
    const listener = loadBalancer.addListener("HttpsListener", {
      port: 443,
      protocol: elbv2.ApplicationProtocol.HTTPS,
      certificates: [certificate],
      defaultAction: elbv2.ListenerAction.fixedResponse(503, {
        contentType: "text/plain",
        messageBody: "CBOM Workbench authentication is being configured.",
      }),
    });
    listener.addCertificates("ApiCertificate", [apiCertificate]);
    loadBalancer.addListener("HttpListener", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultAction: elbv2.ListenerAction.redirect({ protocol: "HTTPS", port: "443", permanent: true }),
    });

    const targetGroup = new elbv2.ApplicationTargetGroup(this, "WebTargetGroup", {
      targetGroupName: "cbom-workbench-web",
      vpc,
      protocol: elbv2.ApplicationProtocol.HTTP,
      port: 3000,
      targetType: elbv2.TargetType.IP,
      deregistrationDelay: cdk.Duration.seconds(30),
      healthCheck: {
        enabled: true,
        path: "/healthz",
        healthyHttpCodes: "200",
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
      },
    });
    const apiTargetGroup = new elbv2.ApplicationTargetGroup(this, "ApiTargetGroup", {
      targetGroupName: "cbom-workbench-api",
      vpc,
      protocol: elbv2.ApplicationProtocol.HTTP,
      port: 8000,
      targetType: elbv2.TargetType.IP,
      deregistrationDelay: cdk.Duration.seconds(30),
      healthCheck: {
        enabled: true,
        path: "/healthz",
        healthyHttpCodes: "200",
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
      },
    });
    listener.addTargetGroups("PublicHealthCheck", {
      priority: 5,
      conditions: [elbv2.ListenerCondition.pathPatterns(["/healthz"])],
      targetGroups: [targetGroup],
    });

    const oidcClientId = requiredContext(this, "oidcClientId");
    const webContainer = webTask.addContainer("web", {
      image: ecs.ContainerImage.fromEcrRepository(webRepository, imageTag),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "web",
        logGroup: webLogGroup,
        mode: ecs.AwsLogDriverMode.BLOCKING,
      }),
      environment: {
        CBOM_API_ORIGIN: "http://127.0.0.1:8000",
        CBOM_AUTH_MODE: "alb-oidc",
        CBOM_ALB_ARN: loadBalancer.loadBalancerArn,
        CBOM_OIDC_CLIENT_ID: oidcClientId,
        CBOM_OIDC_ISSUER: requiredContext(this, "oidcIssuer"),
        NODE_ENV: "production",
        NEXT_TELEMETRY_DISABLED: "1",
      },
      secrets: {
        CBOM_API_BEARER_TOKEN: ecs.Secret.fromSecretsManager(apiBearerSecret),
      },
      healthCheck: {
        command: ["CMD-SHELL", "node -e \"const h=require('os').hostname();fetch('http://'+h+':3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))\""],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(30),
      },
    });
    webContainer.addPortMappings({ containerPort: 3000, protocol: ecs.Protocol.TCP });
    webContainer.addContainerDependencies({
      container: apiContainer,
      condition: ecs.ContainerDependencyCondition.HEALTHY,
    });

    const webService = new ecs.FargateService(this, "WebService", {
      serviceName: "cbom-workbench-web",
      cluster,
      taskDefinition: webTask,
      desiredCount: activateServices ? 1 : 0,
      assignPublicIp: false,
      vpcSubnets: { subnets: privateSubnets },
      securityGroups: [webSecurityGroup],
      circuitBreaker: { rollback: true },
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      healthCheckGracePeriod: cdk.Duration.seconds(60),
    });
    targetGroup.addTarget(webService.loadBalancerTarget({
      containerName: "web",
      containerPort: 3000,
    }));
    apiTargetGroup.addTarget(webService.loadBalancerTarget({
      containerName: "api",
      containerPort: 8000,
    }));

    const jobTask = new ecs.FargateTaskDefinition(this, "JobTask", {
      family: "cbom-workbench-job",
      cpu: 1024,
      memoryLimitMiB: 2048,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });
    jobTask.addToTaskRolePolicy(new iam.PolicyStatement({
      actions: ["s3:ListBucket"],
      resources: [dataBucket.bucketArn],
      conditions: { StringLike: { "s3:prefix": ["transfer/*"] } },
    }));
    jobTask.addToTaskRolePolicy(new iam.PolicyStatement({
      actions: ["s3:GetObject", "s3:GetObjectVersion"],
      resources: [dataBucket.arnForObjects("transfer/*")],
    }));
    jobTask.addContainer("job", {
      image: ecs.ContainerImage.fromEcrRepository(catalogRepository, imageTag),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: "job",
        logGroup: jobLogGroup,
        mode: ecs.AwsLogDriverMode.BLOCKING,
      }),
      environment: {
        PGHOST: database.instanceEndpoint.hostname,
        PGPORT: database.instanceEndpoint.port.toString(),
        PGDATABASE: "cbom_catalog",
        CBOM_SNAPSHOT_BUCKET: dataBucket.bucketName,
        CBOM_INGEST_BUCKET: dataBucket.bucketName,
      },
      secrets: {
        PGUSER: ecs.Secret.fromSecretsManager(databaseSecret, "username"),
        PGPASSWORD: ecs.Secret.fromSecretsManager(databaseSecret, "password"),
      },
    });

    apiContainer.addEnvironment("CBOM_INGEST_BUCKET", dataBucket.bucketName);
    apiContainer.addEnvironment("CBOM_INGEST_ECS_CLUSTER", cluster.clusterArn);
    apiContainer.addEnvironment("CBOM_INGEST_TASK_DEFINITION", jobTask.taskDefinitionArn);
    apiContainer.addEnvironment("CBOM_INGEST_SUBNET_IDS", privateSubnetIds.join(","));
    apiContainer.addEnvironment(
      "CBOM_INGEST_SECURITY_GROUP_IDS",
      jobSecurityGroup.securityGroupId,
    );
    apiContainer.addEnvironment("CBOM_INGEST_CONTAINER_NAME", "job");
    apiContainer.addEnvironment("CBOM_INGEST_LOG_GROUP", jobLogGroup.logGroupName);
    apiContainer.addEnvironment("CBOM_INGEST_LOG_STREAM_PREFIX", "job");
    apiContainer.addEnvironment("CBOM_INGEST_URL_TTL_SECONDS", "3600");
    apiContainer.addEnvironment("CBOM_INGEST_MAX_ACTIVE_JOBS", "3");
    webTask.addToTaskRolePolicy(new iam.PolicyStatement({
      actions: ["s3:PutObject"],
      resources: [dataBucket.arnForObjects("transfer/ingestion/*")],
    }));
    const ingestionJobLogStreamArn = cdk.Arn.format({
      service: "logs",
      resource: "log-group",
      resourceName: `${jobLogGroup.logGroupName}:log-stream:job/job/*`,
      arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME,
    }, this);
    webTask.addToTaskRolePolicy(new iam.PolicyStatement({
      actions: ["logs:GetLogEvents"],
      resources: [ingestionJobLogStreamArn],
    }));
    webTask.addToTaskRolePolicy(new iam.PolicyStatement({
      actions: ["ecs:RunTask"],
      resources: [jobTask.taskDefinitionArn],
      conditions: { ArnEquals: { "ecs:cluster": cluster.clusterArn } },
    }));
    const jobRoleArns = [jobTask.taskRole.roleArn];
    if (jobTask.executionRole) jobRoleArns.push(jobTask.executionRole.roleArn);
    webTask.addToTaskRolePolicy(new iam.PolicyStatement({
      actions: ["iam:PassRole"],
      resources: jobRoleArns,
      conditions: { StringEquals: { "iam:PassedToService": "ecs-tasks.amazonaws.com" } },
    }));

    if (enableOidc) {
      const oidcIssuer = requiredContext(this, "oidcIssuer");
      const oidcAuthorizationEndpoint = requiredContext(this, "oidcAuthorizationEndpoint");
      const oidcTokenEndpoint = requiredContext(this, "oidcTokenEndpoint");
      const oidcUserInfoEndpoint = requiredContext(this, "oidcUserInfoEndpoint");

      listener.addAction("OidcAuthentication", {
        priority: 10,
        conditions: [elbv2.ListenerCondition.hostHeaders([hostname])],
        action: elbv2.ListenerAction.authenticateOidc({
          issuer: oidcIssuer,
          authorizationEndpoint: oidcAuthorizationEndpoint,
          tokenEndpoint: oidcTokenEndpoint,
          userInfoEndpoint: oidcUserInfoEndpoint,
          clientId: oidcClientId,
          clientSecret: oidcSecret.secretValue,
          scope: "openid email groups",
          sessionCookieName: "CBOMAWSELBAuthSessionCookie",
          sessionTimeout: cdk.Duration.hours(8),
          onUnauthenticatedRequest: elbv2.UnauthenticatedAction.AUTHENTICATE,
          next: elbv2.ListenerAction.forward([targetGroup]),
        }),
      });
      listener.addTargetGroups("TokenApi", {
        priority: 7,
        conditions: [elbv2.ListenerCondition.hostHeaders([apiHostname])],
        targetGroups: [apiTargetGroup],
      });
      new route53.ARecord(this, "AliasRecord", {
        zone,
        recordName: hostname,
        target: route53.RecordTarget.fromAlias(new route53Targets.LoadBalancerTarget(loadBalancer)),
      });
      new route53.ARecord(this, "ApiAliasRecord", {
        zone,
        recordName: apiHostname,
        target: route53.RecordTarget.fromAlias(new route53Targets.LoadBalancerTarget(loadBalancer)),
      });
    }

    targetGroup.metrics.unhealthyHostCount().createAlarm(this, "UnhealthyTargetsAlarm", {
      alarmName: "cbom-workbench-dev-unhealthy-targets",
      threshold: 1,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });
    loadBalancer.metrics.httpCodeElb(elbv2.HttpCodeElb.ELB_5XX_COUNT).createAlarm(this, "Alb5xxAlarm", {
      alarmName: "cbom-workbench-dev-alb-5xx",
      threshold: 5,
      evaluationPeriods: 2,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    cdk.Tags.of(this).add("ApplicationName", "CBOM Workbench");
    cdk.Tags.of(this).add("Environment", "NONPROD");
    cdk.Tags.of(this).add("EnvironmentSubcategory", "DEV");
    cdk.Tags.of(this).add("DataClassification", "Cisco Restricted");
    cdk.Tags.of(this).add("IntendedPublic", "False");

    new cdk.CfnOutput(this, "ClusterName", { value: cluster.clusterName });
    new cdk.CfnOutput(this, "WebRepositoryUri", { value: webRepository.repositoryUri });
    new cdk.CfnOutput(this, "CatalogRepositoryUri", { value: catalogRepository.repositoryUri });
    new cdk.CfnOutput(this, "DataBucketName", { value: dataBucket.bucketName });
    new cdk.CfnOutput(this, "DatabaseEndpoint", { value: database.instanceEndpoint.hostname });
    new cdk.CfnOutput(this, "LoadBalancerDnsName", { value: loadBalancer.loadBalancerDnsName });
    new cdk.CfnOutput(this, "OidcSecretName", { value: oidcSecret.secretName });
    new cdk.CfnOutput(this, "JobTaskDefinitionArn", { value: jobTask.taskDefinitionArn });
    new cdk.CfnOutput(this, "JobSecurityGroupId", { value: jobSecurityGroup.securityGroupId });
    new cdk.CfnOutput(this, "PrivateSubnetIds", { value: privateSubnetIds.join(",") });
    new cdk.CfnOutput(this, "Hostname", { value: hostname });
    new cdk.CfnOutput(this, "ApiHostname", { value: apiHostname });
    new cdk.CfnOutput(this, "ApiTokenPepperSecretName", { value: apiTokenPepper.secretName });
    new cdk.CfnOutput(this, "ServicesActivated", { value: String(activateServices) });
    new cdk.CfnOutput(this, "OidcEnabled", { value: String(enableOidc) });
  }
}
