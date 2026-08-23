-- Xiaxia Watch House V1 fresh-install schema for Supabase PostgreSQL.
-- Run once in a new project's SQL Editor. All timeline units are seconds.

create extension if not exists pgcrypto;

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table films (
  film_id uuid primary key default gen_random_uuid(),
  title varchar(300) not null,
  source_type varchar(20) not null check (source_type in ('local','youtube','bilibili','iframe','external')),
  source_url text,
  external_video_id varchar(200),
  duration_seconds double precision check (duration_seconds is null or duration_seconds >= 0),
  subtitle_status varchar(20) not null default 'missing' check (subtitle_status in ('missing','ready','error')),
  subtitle_language varchar(40),
  last_activity_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table subtitle_cues (
  cue_id uuid primary key,
  film_id uuid not null references films(film_id) on delete cascade,
  sequence_number integer not null check (sequence_number > 0),
  start_seconds double precision not null check (start_seconds >= 0),
  end_seconds double precision not null check (end_seconds >= start_seconds),
  text text not null,
  language varchar(40) not null default 'und',
  constraint uq_cue_film_language_sequence unique (film_id, language, sequence_number)
);

create index ix_subtitle_cues_film_time
  on subtitle_cues (film_id, start_seconds, end_seconds);

create table user_progress (
  film_id uuid primary key references films(film_id) on delete cascade,
  actor varchar(20) not null default 'user' check (actor = 'user'),
  current_seconds double precision not null default 0 check (current_seconds >= 0),
  duration_seconds double precision check (duration_seconds is null or duration_seconds >= 0),
  playback_state varchar(20) not null default 'idle'
    check (playback_state in ('playing','paused','seeking','ended','idle')),
  updated_at timestamptz not null default now()
);

create table xiaxia_viewing_state (
  film_id uuid primary key references films(film_id) on delete cascade,
  actor varchar(20) not null default 'xiaxia' check (actor = 'xiaxia'),
  last_timestamp_seconds double precision not null default 0 check (last_timestamp_seconds >= 0),
  last_subtitle_cue_id uuid references subtitle_cues(cue_id) on delete set null,
  chunk_checkpoint integer check (chunk_checkpoint is null or chunk_checkpoint >= 0),
  completed boolean not null default false,
  updated_at timestamptz not null default now()
);

create table user_annotations (
  annotation_id uuid primary key default gen_random_uuid(),
  film_id uuid not null references films(film_id) on delete cascade,
  actor varchar(20) not null default 'user' check (actor = 'user'),
  content_type varchar(30) not null default 'user_annotation' check (content_type = 'user_annotation'),
  start_seconds double precision not null check (start_seconds >= 0),
  end_seconds double precision check (end_seconds is null or end_seconds >= start_seconds),
  cue_id uuid references subtitle_cues(cue_id) on delete set null,
  content text not null check (length(btrim(content)) > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index ix_annotations_film_time on user_annotations (film_id, start_seconds);

create table xiaxia_thoughts (
  thought_id uuid primary key default gen_random_uuid(),
  film_id uuid not null references films(film_id) on delete cascade,
  actor varchar(20) not null default 'xiaxia' check (actor = 'xiaxia'),
  content_type varchar(30) not null default 'xiaxia_thought' check (content_type = 'xiaxia_thought'),
  start_seconds double precision not null check (start_seconds >= 0),
  end_seconds double precision check (end_seconds is null or end_seconds >= start_seconds),
  cue_id uuid references subtitle_cues(cue_id) on delete set null,
  content text not null check (length(btrim(content)) > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index ix_thoughts_film_time on xiaxia_thoughts (film_id, start_seconds);

create table xiaxia_replies (
  reply_id uuid primary key default gen_random_uuid(),
  annotation_id uuid not null references user_annotations(annotation_id) on delete cascade,
  film_id uuid not null references films(film_id) on delete cascade,
  actor varchar(20) not null default 'xiaxia' check (actor = 'xiaxia'),
  content_type varchar(30) not null default 'xiaxia_reply' check (content_type = 'xiaxia_reply'),
  start_seconds double precision not null check (start_seconds >= 0),
  end_seconds double precision check (end_seconds is null or end_seconds >= start_seconds),
  cue_id uuid references subtitle_cues(cue_id) on delete set null,
  content text not null check (length(btrim(content)) > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index ix_replies_film_time on xiaxia_replies (film_id, start_seconds);
create index ix_replies_annotation on xiaxia_replies (annotation_id);

create table watch_state (
  singleton_id integer primary key default 1 check (singleton_id = 1),
  current_film_id uuid references films(film_id) on delete set null,
  updated_at timestamptz not null default now()
);

insert into watch_state (singleton_id, current_film_id)
values (1, null)
on conflict (singleton_id) do nothing;

create trigger films_set_updated_at before update on films
for each row execute function set_updated_at();
create trigger user_annotations_set_updated_at before update on user_annotations
for each row execute function set_updated_at();
create trigger xiaxia_thoughts_set_updated_at before update on xiaxia_thoughts
for each row execute function set_updated_at();
create trigger xiaxia_replies_set_updated_at before update on xiaxia_replies
for each row execute function set_updated_at();
create trigger user_progress_set_updated_at before update on user_progress
for each row execute function set_updated_at();
create trigger xiaxia_viewing_state_set_updated_at before update on xiaxia_viewing_state
for each row execute function set_updated_at();
create trigger watch_state_set_updated_at before update on watch_state
for each row execute function set_updated_at();

-- Storage is intentionally not required in V1. Local video stays in the browser;
-- PostgreSQL stores only metadata, subtitle text, progress, and timeline traces.
