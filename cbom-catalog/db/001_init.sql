BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS catalog_meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schema_migration (
    version text PRIMARY KEY,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO catalog_meta (key, value)
VALUES ('schema_version', '1')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, updated_at = now();

CREATE TABLE IF NOT EXISTS source_collection (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug text NOT NULL UNIQUE,
    display_name text NOT NULL,
    root_uri text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_run (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_collection_id bigint
        CONSTRAINT ingest_run_source_collection_fkey REFERENCES source_collection(id),
    root_path text NOT NULL,
    parser_version text NOT NULL,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'completed_with_errors', 'failed')),
    files_seen integer NOT NULL DEFAULT 0,
    files_loaded integer NOT NULL DEFAULT 0,
    files_linked integer NOT NULL DEFAULT 0,
    files_failed integer NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE IF NOT EXISTS service_group (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug text NOT NULL UNIQUE,
    display_name text NOT NULL,
    source_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sha256 char(64) NOT NULL UNIQUE,
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    document_kind text NOT NULL,
    format_name text,
    spec_version text,
    serial_number text,
    document_version text,
    generated_at_text text,
    generator jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_document jsonb,
    parser_version text NOT NULL,
    warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS source_file (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_collection_id bigint NOT NULL
        CONSTRAINT source_file_source_collection_fkey REFERENCES source_collection(id),
    service_group_id bigint NOT NULL REFERENCES service_group(id),
    document_id bigint REFERENCES document(id),
    last_seen_run_id bigint REFERENCES ingest_run(id),
    source_path text NOT NULL,
    source_uri text,
    filename text NOT NULL,
    media_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    content_sha256 char(64),
    modified_at timestamptz,
    parse_status text NOT NULL
        CHECK (parse_status IN ('loaded', 'linked', 'empty', 'invalid', 'unsupported', 'error')),
    parse_message text,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT source_file_collection_path_key UNIQUE (source_collection_id, source_path),
    CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS artifact (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_key text NOT NULL UNIQUE,
    artifact_type text,
    name text,
    version text,
    purl text,
    cpe text,
    registry text,
    repository text,
    tag text,
    digest text,
    extra jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_artifact (
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    artifact_id bigint NOT NULL REFERENCES artifact(id),
    role text NOT NULL,
    confidence numeric(4,3) NOT NULL DEFAULT 1.000 CHECK (confidence BETWEEN 0 AND 1),
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (document_id, artifact_id, role)
);

CREATE TABLE IF NOT EXISTS component (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    identity_hash char(64) NOT NULL UNIQUE,
    canonical_purl text,
    cpe text,
    component_type text,
    namespace text,
    name text NOT NULL,
    version text,
    publisher text,
    supplier text,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_component (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    component_id bigint NOT NULL REFERENCES component(id),
    bom_ref text NOT NULL,
    source_bom_ref text NOT NULL,
    scope text,
    is_subject boolean NOT NULL DEFAULT false,
    hashes jsonb NOT NULL DEFAULT '[]'::jsonb,
    licenses jsonb NOT NULL DEFAULT '[]'::jsonb,
    external_references jsonb NOT NULL DEFAULT '[]'::jsonb,
    properties jsonb NOT NULL DEFAULT '[]'::jsonb,
    crypto_properties jsonb,
    evidence jsonb,
    raw_extra jsonb NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT document_component_document_bom_ref_key UNIQUE (document_id, bom_ref),
    CONSTRAINT document_component_document_id_id_key UNIQUE (document_id, id)
);

CREATE TABLE IF NOT EXISTS document_property (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    property_scope text NOT NULL,
    property_name text NOT NULL,
    property_value text,
    property_namespace text,
    UNIQUE (document_id, property_scope, ordinal)
);

CREATE TABLE IF NOT EXISTS component_property (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id bigint NOT NULL REFERENCES document_component(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    property_name text NOT NULL,
    property_value text,
    property_namespace text,
    UNIQUE (occurrence_id, ordinal)
);

CREATE TABLE IF NOT EXISTS component_license (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurrence_id bigint NOT NULL REFERENCES document_component(id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    license_id text,
    license_name text,
    expression text,
    acknowledgement text,
    raw_license jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (occurrence_id, ordinal)
);

CREATE TABLE IF NOT EXISTS dependency_edge (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    from_occurrence_id bigint,
    to_occurrence_id bigint,
    from_ref text NOT NULL,
    to_ref text NOT NULL,
    relationship_type text NOT NULL DEFAULT 'DEPENDS_ON',
    resolution_status text NOT NULL DEFAULT 'resolved'
        CHECK (resolution_status IN ('resolved', 'partial', 'ambiguous', 'external')),
    raw_edge jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, from_ref, to_ref, relationship_type),
    CONSTRAINT dependency_edge_from_occurrence_fk
        FOREIGN KEY (document_id, from_occurrence_id)
        REFERENCES document_component(document_id, id) ON DELETE CASCADE,
    CONSTRAINT dependency_edge_to_occurrence_fk
        FOREIGN KEY (document_id, to_occurrence_id)
        REFERENCES document_component(document_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vulnerability (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name text NOT NULL DEFAULT '',
    vulnerability_id text NOT NULL,
    source_url text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_name, vulnerability_id)
);

CREATE TABLE IF NOT EXISTS document_vulnerability (
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    vulnerability_id bigint NOT NULL REFERENCES vulnerability(id),
    ratings jsonb NOT NULL DEFAULT '[]'::jsonb,
    analysis jsonb,
    description text,
    detail text,
    advisories jsonb NOT NULL DEFAULT '[]'::jsonb,
    properties jsonb NOT NULL DEFAULT '[]'::jsonb,
    raw_vulnerability jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (document_id, vulnerability_id)
);

CREATE TABLE IF NOT EXISTS vulnerability_affect (
    document_id bigint NOT NULL,
    vulnerability_id bigint NOT NULL,
    affected_ref text NOT NULL,
    versions jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (document_id, vulnerability_id, affected_ref),
    FOREIGN KEY (document_id, vulnerability_id)
        REFERENCES document_vulnerability(document_id, vulnerability_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS spdx_file (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    spdx_id text NOT NULL,
    file_name text,
    checksums jsonb NOT NULL DEFAULT '[]'::jsonb,
    license_concluded text,
    license_info_in_file jsonb NOT NULL DEFAULT '[]'::jsonb,
    copyright_text text,
    raw_file jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, spdx_id)
);

CREATE TABLE IF NOT EXISTS external_record (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    artifact_id bigint REFERENCES artifact(id),
    parent_record_id bigint REFERENCES external_record(id) ON DELETE CASCADE,
    record_type text NOT NULL,
    external_id text NOT NULL,
    observed_at_text text,
    provider text,
    payload_sha256 char(64) NOT NULL,
    data jsonb NOT NULL,
    CONSTRAINT external_record_immutable_observation_key
        UNIQUE (document_id, record_type, external_id, payload_sha256),
    CHECK (payload_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS ingest_issue (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingest_run_id bigint REFERENCES ingest_run(id) ON DELETE SET NULL,
    source_file_id bigint REFERENCES source_file(id) ON DELETE CASCADE,
    document_id bigint REFERENCES document(id) ON DELETE CASCADE,
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    issue_code text NOT NULL,
    message text NOT NULL,
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_file_collection_path
    ON source_file(source_collection_id, source_path);
CREATE INDEX IF NOT EXISTS idx_source_file_group ON source_file(service_group_id);
CREATE INDEX IF NOT EXISTS idx_source_file_document ON source_file(document_id);
CREATE INDEX IF NOT EXISTS idx_source_file_status ON source_file(parse_status);
CREATE INDEX IF NOT EXISTS idx_document_kind_spec ON document(document_kind, spec_version);
CREATE INDEX IF NOT EXISTS idx_document_serial ON document(serial_number);
CREATE INDEX IF NOT EXISTS idx_artifact_purl ON artifact(purl) WHERE purl IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_artifact_digest ON artifact(digest) WHERE digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_artifact_name_trgm ON artifact USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_component_purl ON component(canonical_purl) WHERE canonical_purl IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_component_cpe ON component(cpe) WHERE cpe IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_component_name_version ON component(name, version);
CREATE INDEX IF NOT EXISTS idx_component_name_trgm ON component USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_document_component_document ON document_component(document_id);
CREATE INDEX IF NOT EXISTS idx_document_component_component ON document_component(component_id);
CREATE INDEX IF NOT EXISTS idx_document_component_source_ref
    ON document_component(document_id, source_bom_ref);
CREATE INDEX IF NOT EXISTS idx_document_property_name_value
    ON document_property(property_name, property_value);
CREATE INDEX IF NOT EXISTS idx_document_component_properties_gin
    ON document_component USING gin (properties jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_document_component_crypto_gin
    ON document_component USING gin (crypto_properties jsonb_path_ops)
    WHERE crypto_properties IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_component_property_name_value
    ON component_property(property_name, property_value);
CREATE INDEX IF NOT EXISTS idx_component_property_value_trgm
    ON component_property USING gin (property_value gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_dependency_document_from ON dependency_edge(document_id, from_ref);
CREATE INDEX IF NOT EXISTS idx_dependency_document_to ON dependency_edge(document_id, to_ref);
CREATE INDEX IF NOT EXISTS idx_dependency_type_from
    ON dependency_edge(document_id, relationship_type, from_ref);
CREATE INDEX IF NOT EXISTS idx_component_license_id ON component_license(license_id);
CREATE INDEX IF NOT EXISTS idx_component_license_expression ON component_license(expression);
CREATE INDEX IF NOT EXISTS idx_external_record_type ON external_record(record_type);
CREATE INDEX IF NOT EXISTS idx_external_record_data_gin
    ON external_record USING gin (data jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_ingest_issue_code ON ingest_issue(issue_code, severity);

CREATE OR REPLACE VIEW v_document_inventory AS
SELECT
    d.id AS document_id,
    d.sha256,
    d.document_kind,
    d.format_name,
    d.spec_version,
    d.serial_number,
    d.generated_at_text,
    count(sf.id) AS source_alias_count,
    array_agg(DISTINCT sc.slug ORDER BY sc.slug) AS source_collections,
    array_agg(DISTINCT sg.display_name ORDER BY sg.display_name) AS service_groups,
    array_agg(sf.source_path ORDER BY sc.slug, sf.source_path) AS source_paths,
    array_remove(array_agg(sf.source_uri ORDER BY sc.slug, sf.source_path), NULL) AS source_uris
FROM document d
JOIN source_file sf ON sf.document_id = d.id
JOIN source_collection sc ON sc.id = sf.source_collection_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY d.id;

CREATE OR REPLACE VIEW v_component_usage AS
SELECT
    c.id AS component_id,
    c.component_type,
    c.namespace,
    c.name,
    c.version,
    c.canonical_purl,
    c.cpe,
    count(DISTINCT dc.document_id) AS document_count,
    array_agg(DISTINCT sg.display_name ORDER BY sg.display_name) AS service_groups
FROM component c
JOIN document_component dc ON dc.component_id = c.id
JOIN source_file sf ON sf.document_id = dc.document_id
JOIN service_group sg ON sg.id = sf.service_group_id
GROUP BY c.id;

CREATE OR REPLACE VIEW v_format_coverage AS
SELECT
    d.document_kind,
    coalesce(d.format_name, '') AS format_name,
    coalesce(d.spec_version, '') AS spec_version,
    count(DISTINCT d.id) AS unique_documents,
    count(DISTINCT sf.id) AS source_files,
    count(DISTINCT dc.id) AS component_occurrences
FROM document d
LEFT JOIN source_file sf ON sf.document_id = d.id
LEFT JOIN document_component dc ON dc.document_id = d.id
GROUP BY d.document_kind, d.format_name, d.spec_version;

CREATE OR REPLACE VIEW v_duplicate_source_content AS
SELECT *
FROM v_document_inventory
WHERE source_alias_count > 1;

INSERT INTO schema_migration (version, description)
VALUES ('001', 'initial catalog schema')
ON CONFLICT (version) DO NOTHING;

COMMIT;
