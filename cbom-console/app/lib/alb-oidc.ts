type AlbJwtHeader = {
  alg?: string;
  client?: string;
  exp?: number;
  kid?: string;
  signer?: string;
};

type VerificationResult = { ok: true; subject?: string } | { ok: false; reason: string };

const keyCache = new Map<string, Promise<CryptoKey>>();
const GOVCLOUD_KEY_ORIGINS: Record<string, string> = {
  "us-gov-east-1": "https://s3-us-gov-east-1.amazonaws.com/aws-elb-public-keys-prod-us-gov-east-1",
  "us-gov-west-1": "https://s3-us-gov-west-1.amazonaws.com/aws-elb-public-keys-prod-us-gov-west-1",
};

function bytesFromBinary(binary: string): ArrayBuffer {
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes.buffer;
}

function decodeBase64Url(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  return bytesFromBinary(atob(padded));
}

function decodeJson<T>(value: string): T {
  return JSON.parse(new TextDecoder().decode(decodeBase64Url(value))) as T;
}

function signerRegion(signer: string): string | undefined {
  const match = signer.match(/^arn:aws-us-gov:elasticloadbalancing:([^:]+):\d{12}:loadbalancer\/app\/[A-Za-z0-9-]+\/[a-f0-9]+$/);
  return match?.[1];
}

async function signingKey(region: string, kid: string): Promise<CryptoKey> {
  if (!/^[A-Za-z0-9-]{1,128}$/.test(kid)) throw new Error("Invalid ALB key identifier");
  const origin = GOVCLOUD_KEY_ORIGINS[region];
  if (!origin) throw new Error("Unsupported ALB signing region");
  const cacheKey = `${region}:${kid}`;
  let pending = keyCache.get(cacheKey);
  if (!pending) {
    pending = (async () => {
      const response = await fetch(`${origin}/${kid}`, { cache: "force-cache" });
      if (!response.ok) throw new Error("Unable to retrieve ALB signing key");
      const pem = await response.text();
      const encoded = pem.replace(/-----BEGIN PUBLIC KEY-----|-----END PUBLIC KEY-----|\s/g, "");
      return crypto.subtle.importKey(
        "spki",
        bytesFromBinary(atob(encoded)),
        { name: "ECDSA", namedCurve: "P-256" },
        false,
        ["verify"],
      );
    })();
    keyCache.set(cacheKey, pending);
  }
  try {
    return await pending;
  } catch (error) {
    keyCache.delete(cacheKey);
    throw error;
  }
}

export async function verifyAlbOidcToken(token: string): Promise<VerificationResult> {
  const expectedSigner = process.env.CBOM_ALB_ARN?.trim();
  const expectedClient = process.env.CBOM_OIDC_CLIENT_ID?.trim();
  if (!expectedSigner || !expectedClient) return { ok: false, reason: "Cloud authentication is not configured" };

  try {
    const [encodedHeader, encodedPayload, encodedSignature, extra] = token.split(".");
    if (!encodedHeader || !encodedPayload || !encodedSignature || extra) return { ok: false, reason: "Malformed identity token" };
    const header = decodeJson<AlbJwtHeader>(encodedHeader);
    if (header.alg !== "ES256" || !header.kid || header.signer !== expectedSigner || header.client !== expectedClient) {
      return { ok: false, reason: "Identity token does not match this deployment" };
    }
    if (!header.exp || header.exp <= Math.floor(Date.now() / 1000)) return { ok: false, reason: "Identity session has expired" };
    const region = signerRegion(header.signer);
    if (!region) return { ok: false, reason: "Unrecognized load-balancer signer" };
    const key = await signingKey(region, header.kid);
    const verified = await crypto.subtle.verify(
      { name: "ECDSA", hash: "SHA-256" },
      key,
      decodeBase64Url(encodedSignature),
      new TextEncoder().encode(`${encodedHeader}.${encodedPayload}`),
    );
    if (!verified) return { ok: false, reason: "Identity signature is invalid" };
    const claims = decodeJson<{ sub?: string }>(encodedPayload);
    return { ok: true, subject: claims.sub };
  } catch {
    return { ok: false, reason: "Identity token could not be verified" };
  }
}
