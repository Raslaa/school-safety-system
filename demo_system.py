-- Run once in Supabase SQL Editor.
-- Assumes public.students.id is the UUID primary key used by the existing app.

create table if not exists public.student_location_shares (
    student_id uuid primary key references public.students(id) on delete cascade,
    token_hash text not null unique,
    enabled boolean not null default true,
    created_at timestamptz not null default now()
);

-- One independent, revocable portal URL for each guardian and child.
create table if not exists public.student_parent_portal_links (
    id uuid primary key default gen_random_uuid(),
    student_id uuid not null references public.students(id) on delete cascade,
    guardian_key text not null,
    guardian_name text not null,
    token_hash text not null unique,
    enabled boolean not null default true,
    created_at timestamptz not null default now(),
    unique (student_id, guardian_key)
);

create table if not exists public.student_live_locations (
    student_id uuid primary key references public.students(id) on delete cascade,
    latitude double precision not null check (latitude between -90 and 90),
    longitude double precision not null check (longitude between -180 and 180),
    accuracy_meters double precision not null check (accuracy_meters between 0 and 10000),
    captured_at timestamptz not null,
    updated_at timestamptz not null default now()
);

-- Opt-in live location from the scanner's phone, not verified student tracking.
create table if not exists public.student_tag_scan_locations (
    student_id uuid primary key references public.students(id) on delete cascade,
    latitude double precision not null check (latitude between -90 and 90),
    longitude double precision not null check (longitude between -180 and 180),
    accuracy_meters double precision not null check (accuracy_meters between 0 and 10000),
    captured_at timestamptz not null,
    updated_at timestamptz not null default now(),
    sharing_active boolean not null default false
);

-- Add the live-session flag to installations created with the earlier report-only script.
alter table public.student_tag_scan_locations
    add column if not exists sharing_active boolean not null default false;

create index if not exists student_live_locations_captured_at_idx
    on public.student_live_locations (captured_at desc);
create index if not exists student_tag_scan_locations_captured_at_idx
    on public.student_tag_scan_locations (captured_at desc);

alter table public.student_location_shares enable row level security;
alter table public.student_parent_portal_links enable row level security;
alter table public.student_live_locations enable row level security;
alter table public.student_tag_scan_locations enable row level security;

revoke all on table public.student_location_shares from anon, authenticated;
revoke all on table public.student_parent_portal_links from anon, authenticated;
revoke all on table public.student_live_locations from anon, authenticated;
revoke all on table public.student_tag_scan_locations from anon, authenticated;
grant all on table public.student_location_shares to service_role;
grant all on table public.student_parent_portal_links to service_role;
grant all on table public.student_live_locations to service_role;
grant all on table public.student_tag_scan_locations to service_role;
