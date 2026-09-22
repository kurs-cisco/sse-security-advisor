import * as cdk from "aws-cdk-lib";
import * as acm from "aws-cdk-lib/aws-certificatemanager";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
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
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: "api", logGroup: apiLogGroup }),
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
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: "web", logGroup: webLogGroup }),
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
      actions: ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket"],
      resources: [dataBucket.bucketArn, dataBucket.arnForObjects("*")],
    }));
    jobTask.addContainer("job", {
      image: ecs.ContainerImage.fromEcrRepository(catalogRepository, imageTag),
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: "job", logGroup: jobLogGroup }),
      environment: {
        PGHOST: database.instanceEndpoint.hostname,
        PGPORT: database.instanceEndpoint.port.toString(),
        PGDATABASE: "cbom_catalog",
        CBOM_SNAPSHOT_BUCKET: dataBucket.bucketName,
      },
      secrets: {
        PGUSER: ecs.Secret.fromSecretsManager(databaseSecret, "username"),
        PGPASSWORD: ecs.Secret.fromSecretsManager(databaseSecret, "password"),
      },
    });

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
