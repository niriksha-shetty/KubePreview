-- Seed script for KubePreview Ephemeral Mock Database

CREATE TABLE IF NOT EXISTS preview_features (
    id SERIAL PRIMARY KEY,
    feature_key VARCHAR(100) NOT NULL UNIQUE,
    feature_name VARCHAR(250) NOT NULL,
    status VARCHAR(50) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO preview_features (feature_key, feature_name, status) VALUES
('FEAT-101', 'Multi-Tenant Namespace Isolation & Quotas', 'ACTIVE'),
('FEAT-102', 'Automated Preview Lifecycle & TTL Sweeper', 'PENDING'),
('FEAT-103', 'Dynamic NGINX Ingress Routing via nip.io', 'ACTIVE'),
('FEAT-104', 'Ephemeral PostgreSQL Database Auto-Provisioning', 'ACTIVE'),
('FEAT-105', 'GitLab/GitHub Webhook Pull Request Orchestration', 'PLANNED')
ON CONFLICT (feature_key) DO NOTHING;
