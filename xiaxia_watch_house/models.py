from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Film(Base, TimestampMixin):
    __tablename__ = "films"
    __table_args__ = (
        CheckConstraint(
            "source_type in ('local','youtube','bilibili','iframe','external')",
            name="films_source_type_check",
        ),
        CheckConstraint("duration_seconds is null or duration_seconds >= 0", name="films_duration_check"),
        CheckConstraint("subtitle_status in ('missing','ready','error')", name="films_subtitle_status_check"),
    )

    film_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    external_video_id: Mapped[str | None] = mapped_column(String(200))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    subtitle_status: Mapped[str] = mapped_column(String(20), nullable=False, default="missing")
    subtitle_language: Mapped[str | None] = mapped_column(String(40))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    cues: Mapped[list[SubtitleCue]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    annotations: Mapped[list[UserAnnotation]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    thoughts: Mapped[list[XiaxiaThought]] = relationship(cascade="all, delete-orphan", passive_deletes=True)
    fleeting_traces: Mapped[list[FleetingTrace]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class SubtitleCue(Base):
    __tablename__ = "subtitle_cues"
    __table_args__ = (
        UniqueConstraint("film_id", "language", "sequence_number", name="uq_cue_film_language_sequence"),
        CheckConstraint("start_seconds >= 0", name="cue_start_check"),
        CheckConstraint("end_seconds >= start_seconds", name="cue_end_check"),
        CheckConstraint("sequence_number > 0", name="cue_sequence_check"),
        Index("ix_subtitle_cues_film_time", "film_id", "start_seconds", "end_seconds"),
    )

    cue_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="und")


class UserProgress(Base):
    __tablename__ = "user_progress"
    __table_args__ = (
        CheckConstraint("actor = 'user'", name="user_progress_actor_check"),
        CheckConstraint("current_seconds >= 0", name="user_progress_seconds_check"),
        CheckConstraint("duration_seconds is null or duration_seconds >= 0", name="user_progress_duration_check"),
        CheckConstraint(
            "playback_state in ('playing','paused','seeking','ended','idle')",
            name="user_progress_state_check",
        ),
        CheckConstraint(
            "watch_intent is null or watch_intent = 'rewatch'",
            name="user_progress_intent_check",
        ),
    )

    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), primary_key=True
    )
    actor: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    current_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    playback_state: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    watch_intent: Mapped[str | None] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class XiaxiaViewingState(Base):
    __tablename__ = "xiaxia_viewing_state"
    __table_args__ = (
        CheckConstraint("actor = 'xiaxia'", name="xiaxia_progress_actor_check"),
        CheckConstraint("last_timestamp_seconds >= 0", name="xiaxia_progress_seconds_check"),
        CheckConstraint("chunk_checkpoint is null or chunk_checkpoint >= 0", name="xiaxia_chunk_check"),
    )

    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), primary_key=True
    )
    actor: Mapped[str] = mapped_column(String(20), nullable=False, default="xiaxia")
    last_timestamp_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    last_subtitle_cue_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("subtitle_cues.cue_id", ondelete="SET NULL")
    )
    chunk_checkpoint: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserAnnotation(Base, TimestampMixin):
    __tablename__ = "user_annotations"
    __table_args__ = (
        CheckConstraint("actor = 'user'", name="annotation_actor_check"),
        CheckConstraint("content_type = 'user_annotation'", name="annotation_type_check"),
        CheckConstraint("start_seconds >= 0", name="annotation_start_check"),
        CheckConstraint("end_seconds is null or end_seconds >= start_seconds", name="annotation_end_check"),
        Index("ix_annotations_film_time", "film_id", "start_seconds"),
    )

    annotation_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_uuid)
    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    content_type: Mapped[str] = mapped_column(String(30), nullable=False, default="user_annotation")
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float | None] = mapped_column(Float)
    cue_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("subtitle_cues.cue_id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    replies: Mapped[list[XiaxiaReply]] = relationship(cascade="all, delete-orphan", passive_deletes=True)


class XiaxiaThought(Base, TimestampMixin):
    __tablename__ = "xiaxia_thoughts"
    __table_args__ = (
        CheckConstraint("actor = 'xiaxia'", name="thought_actor_check"),
        CheckConstraint("content_type = 'xiaxia_thought'", name="thought_type_check"),
        CheckConstraint("start_seconds >= 0", name="thought_start_check"),
        CheckConstraint("end_seconds is null or end_seconds >= start_seconds", name="thought_end_check"),
        Index("ix_thoughts_film_time", "film_id", "start_seconds"),
    )

    thought_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_uuid)
    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(20), nullable=False, default="xiaxia")
    content_type: Mapped[str] = mapped_column(String(30), nullable=False, default="xiaxia_thought")
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float | None] = mapped_column(Float)
    cue_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("subtitle_cues.cue_id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)


class XiaxiaReply(Base, TimestampMixin):
    __tablename__ = "xiaxia_replies"
    __table_args__ = (
        CheckConstraint("actor = 'xiaxia'", name="reply_actor_check"),
        CheckConstraint("content_type = 'xiaxia_reply'", name="reply_type_check"),
        CheckConstraint("start_seconds >= 0", name="reply_start_check"),
        CheckConstraint("end_seconds is null or end_seconds >= start_seconds", name="reply_end_check"),
        Index("ix_replies_film_time", "film_id", "start_seconds"),
    )

    reply_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_uuid)
    annotation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("user_annotations.annotation_id", ondelete="CASCADE"), nullable=False
    )
    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(20), nullable=False, default="xiaxia")
    content_type: Mapped[str] = mapped_column(String(30), nullable=False, default="xiaxia_reply")
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float | None] = mapped_column(Float)
    cue_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("subtitle_cues.cue_id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)


def default_trace_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=30)


class FleetingTrace(Base, TimestampMixin):
    __tablename__ = "fleeting_traces"
    __table_args__ = (
        CheckConstraint("actor in ('user','xiaxia')", name="fleeting_trace_actor_check"),
        CheckConstraint("content_type = 'fleeting_trace'", name="fleeting_trace_type_check"),
        CheckConstraint("start_seconds >= 0", name="fleeting_trace_start_check"),
        CheckConstraint(
            "end_seconds is null or end_seconds >= start_seconds",
            name="fleeting_trace_end_check",
        ),
        CheckConstraint("length(content) <= 160", name="fleeting_trace_length_check"),
        Index("ix_fleeting_traces_film_time", "film_id", "start_seconds"),
        Index("ix_fleeting_traces_expiry", "expires_at"),
    )

    trace_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_uuid)
    film_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="CASCADE"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(30), nullable=False, default="fleeting_trace")
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float | None] = mapped_column(Float)
    cue_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("subtitle_cues.cue_id", ondelete="SET NULL")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=default_trace_expiry
    )


class WatchState(Base):
    __tablename__ = "watch_state"
    __table_args__ = (CheckConstraint("singleton_id = 1", name="watch_state_singleton_check"),)

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    current_film_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("films.film_id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
