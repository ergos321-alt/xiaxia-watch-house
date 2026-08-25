-- Xiaxia Watch House V1.1 -> V2 additive migration for Supabase PostgreSQL.
-- Run once in SQL Editor before deploying V2. This migration does not delete or rewrite V1.1 data.

begin;

alter table user_progress
  add column if not exists watch_intent varchar(20);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'user_progress_intent_check'
  ) then
    alter table user_progress
      add constraint user_progress_intent_check
      check (watch_intent is null or watch_intent = 'rewatch');
  end if;
end;
$$;

create table if not exists fleeting_traces (
  trace_id uuid primary key default gen_random_uuid(),
  film_id uuid not null references films(film_id) on delete cascade,
  actor varchar(20) not null check (actor in ('user','xiaxia')),
  content_type varchar(30) not null default 'fleeting_trace' check (content_type = 'fleeting_trace'),
  start_seconds double precision not null check (start_seconds >= 0),
  end_seconds double precision check (end_seconds is null or end_seconds >= start_seconds),
  cue_id uuid references subtitle_cues(cue_id) on delete set null,
  content text not null check (length(btrim(content)) > 0 and length(content) <= 160),
  expires_at timestamptz not null default (now() + interval '30 days'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ix_fleeting_traces_film_time
  on fleeting_traces (film_id, start_seconds);
create index if not exists ix_fleeting_traces_expiry
  on fleeting_traces (expires_at);

drop trigger if exists fleeting_traces_set_updated_at on fleeting_traces;
create trigger fleeting_traces_set_updated_at before update on fleeting_traces
for each row execute function set_updated_at();

commit;

-- Existing films, subtitle_cues, progress rows, annotations, thoughts, replies,
-- and watch_state are intentionally untouched. V1.1 thoughts remain permanent thoughts.
