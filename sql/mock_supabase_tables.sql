-- State for discovery/collection scheduling and test-project publication.
-- Apply only to the dedicated test Supabase project.
create extension if not exists pgcrypto;
create table if not exists pipeline_state (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists pipeline_sources (
  canonical_url text primary key,
  title text not null,
  first_seen_at timestamptz not null default now(),
  last_collected_at timestamptz
);

create table if not exists pipeline_deals (
  id uuid primary key default gen_random_uuid(),
  fingerprint text not null unique,
  title text not null,
  business_name text not null,
  source_url text not null,
  evidence text not null,
  created_at timestamptz not null default now()
);
