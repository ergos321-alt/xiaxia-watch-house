from datetime import datetime, timezone


# =========================
# Short-term History 2.0
#
# 这一层只整理事实。
#
# 它可以说：
# - ChatGPT 大约使用了多久
# - Chrome 出现多少次
# - 屏幕亮了多久
# - 有多少次锁屏 / 解锁
#
# 它不会推断：
# - 用户在工作
# - 用户在摸鱼
# - 用户在折腾地图
# - 用户为什么打开某个 App
#
# 这些更高层的理解留给 Xiaxia。
# =========================


DEFAULT_HISTORY_TYPES = {
    "apps",
    "screen",
    "interaction"
}

SUPPORTED_HISTORY_TYPES = {
    "apps",
    "screen",
    "interaction"
}


# =========================
# 基础工具
# =========================

def _safe_int(
    value
):
    try:
        if value is None:
            return None

        return int(
            value
        )

    except Exception:
        return None


def _safe_float(
    value
):
    try:
        if value is None:
            return None

        return float(
            value
        )

    except Exception:
        return None


def epoch_to_iso(
    epoch_value
):
    epoch_value = (
        _safe_int(
            epoch_value
        )
    )

    if epoch_value is None:
        return None

    try:
        return datetime.fromtimestamp(
            epoch_value,
            tz=timezone.utc
        ).isoformat()

    except Exception:
        return None


def iso_to_epoch(
    value
):
    if not isinstance(
        value,
        str
    ):
        return None

    value = value.strip()

    if not value:
        return None

    try:
        # 支持 Z
        if value.endswith(
            "Z"
        ):
            value = (
                value[:-1]
                + "+00:00"
            )

        parsed = (
            datetime.fromisoformat(
                value
            )
        )

        if parsed.tzinfo is None:
            parsed = (
                parsed.replace(
                    tzinfo=timezone.utc
                )
            )

        return int(
            parsed.timestamp()
        )

    except Exception:
        return None


def event_epoch(
    event
):
    if not isinstance(
        event,
        dict
    ):
        return None

    event_time = (
        _safe_int(
            event.get(
                "event_time"
            )
        )
    )

    if event_time is not None:
        return event_time

    event_at = (
        event.get(
            "event_at"
        )
    )

    if isinstance(
        event_at,
        str
    ):
        return (
            iso_to_epoch(
                event_at
            )
        )

    at = (
        event.get(
            "at"
        )
    )

    if isinstance(
        at,
        str
    ):
        return (
            iso_to_epoch(
                at
            )
        )

    return None


def clamp(
    value,
    minimum,
    maximum
):
    return max(
        minimum,
        min(
            value,
            maximum
        )
    )


# =========================
# History 类型解析
# =========================

def parse_history_types(
    value
):
    """
    支持：

    None
    "all"
    "apps"
    "apps,screen"
    ["apps", "screen"]

    返回 set。
    """

    if value is None:
        return set(
            DEFAULT_HISTORY_TYPES
        )

    if isinstance(
        value,
        str
    ):
        raw_items = [
            item.strip().lower()
            for item
            in value.split(",")
            if item.strip()
        ]

    elif isinstance(
        value,
        (list, tuple, set)
    ):
        raw_items = [
            str(item)
            .strip()
            .lower()
            for item
            in value
            if str(item).strip()
        ]

    else:
        return set(
            DEFAULT_HISTORY_TYPES
        )

    if not raw_items:
        return set(
            DEFAULT_HISTORY_TYPES
        )

    if "all" in raw_items:
        return set(
            SUPPORTED_HISTORY_TYPES
        )

    selected = {
        item
        for item
        in raw_items
        if item
        in SUPPORTED_HISTORY_TYPES
    }

    if not selected:
        return set(
            DEFAULT_HISTORY_TYPES
        )

    return selected


# =========================
# 事件分类
# =========================

def event_category(
    event_type
):
    if event_type == "app_changed":
        return "apps"

    if event_type in (
        "screen_on",
        "screen_off",
        "lock",
        "unlock"
    ):
        return "screen"

    if event_type in (
        "interaction",
        "initial"
    ):
        return "interaction"

    return None


# =========================
# Event 标准化
# =========================

def normalize_event(
    event
):
    if not isinstance(
        event,
        dict
    ):
        return None

    timestamp = (
        event_epoch(
            event
        )
    )

    if timestamp is None:
        return None

    event_type = (
        event.get(
            "event_type"
        )
    )

    if event_type is None:
        event_type = (
            event.get(
                "event"
            )
        )

    if not isinstance(
        event_type,
        str
    ):
        return None

    event_type = (
        event_type
        .strip()
        .lower()
    )

    if not event_type:
        return None

    app_name = (
        event.get(
            "app_name"
        )
    )

    app_package = (
        event.get(
            "app_package"
        )
    )

    if app_package is None:
        app_package = (
            event.get(
                "package_name"
            )
        )

    screen = (
        event.get(
            "screen"
        )
    )

    locked = (
        event.get(
            "locked"
        )
    )

    if isinstance(
        locked,
        str
    ):
        value = (
            locked
            .strip()
            .lower()
        )

        if value == "true":
            locked = True

        elif value == "false":
            locked = False

        else:
            locked = None

    return {
        "event_type": (
            event_type
        ),

        "event_time": (
            timestamp
        ),

        "event_at": (
            epoch_to_iso(
                timestamp
            )
        ),

        "category": (
            event_category(
                event_type
            )
        ),

        "app_name": (
            app_name
        ),

        "app_package": (
            app_package
        ),

        "screen": (
            screen
        ),

        "locked": (
            locked
        )
    }


def normalize_events(
    events
):
    if not isinstance(
        events,
        list
    ):
        return []

    normalized = []

    for event in events:
        item = (
            normalize_event(
                event
            )
        )

        if item is None:
            continue

        normalized.append(
            item
        )

    normalized.sort(
        key=lambda item: (
            item[
                "event_time"
            ]
        )
    )

    return normalized


# =========================
# App 聚合工具
# =========================

def _app_key(
    app_name,
    package_name
):
    if package_name:
        return (
            "package:"
            + str(
                package_name
            )
        )

    if app_name:
        return (
            "name:"
            + str(
                app_name
            )
        )

    return None


def _ensure_app_record(
    usage,
    app_name,
    package_name
):
    key = (
        _app_key(
            app_name,
            package_name
        )
    )

    if key is None:
        return None

    if key not in usage:
        usage[
            key
        ] = {
            "app_name": (
                app_name
            ),

            "package_name": (
                package_name
            ),

            "approx_seconds": 0.0,

            "switch_count": 0,

            "first_seen_at": None,

            "last_seen_at": None
        }

    record = usage[
        key
    ]

    if (
        not record.get(
            "app_name"
        )
        and app_name
    ):
        record[
            "app_name"
        ] = app_name

    if (
        not record.get(
            "package_name"
        )
        and package_name
    ):
        record[
            "package_name"
        ] = package_name

    return record


def _add_app_duration(
    usage,
    app_name,
    package_name,
    seconds
):
    if seconds is None:
        return

    seconds = (
        _safe_float(
            seconds
        )
    )

    if (
        seconds is None
        or seconds <= 0
    ):
        return

    record = (
        _ensure_app_record(
            usage,
            app_name,
            package_name
        )
    )

    if record is None:
        return

    record[
        "approx_seconds"
    ] += seconds


# =========================
# 状态更新
# =========================

def _apply_event_to_state(
    state,
    event
):
    event_type = (
        event.get(
            "event_type"
        )
    )

    if event_type == "app_changed":

        state[
            "app_name"
        ] = (
            event.get(
                "app_name"
            )
        )

        state[
            "app_package"
        ] = (
            event.get(
                "app_package"
            )
        )

    elif event_type == "screen_off":

        state[
            "screen"
        ] = "off"

        locked = (
            event.get(
                "locked"
            )
        )

        if locked is not None:
            state[
                "locked"
            ] = locked

    elif event_type == "screen_on":

        state[
            "screen"
        ] = "on"

        locked = (
            event.get(
                "locked"
            )
        )

        if locked is not None:
            state[
                "locked"
            ] = locked

    elif event_type == "lock":

        state[
            "locked"
        ] = True

        screen = (
            event.get(
                "screen"
            )
        )

        if screen in (
            "on",
            "off"
        ):
            state[
                "screen"
            ] = screen

    elif event_type == "unlock":

        state[
            "locked"
        ] = False

        screen = (
            event.get(
                "screen"
            )
        )

        if screen in (
            "on",
            "off"
        ):
            state[
                "screen"
            ] = screen

    # 某些数据库行会同时携带
    # 当前 screen / locked 状态。
    # 在事件本身没有明确改变它们时，
    # 可以用于补全未知状态。

    event_screen = (
        event.get(
            "screen"
        )
    )

    event_locked = (
        event.get(
            "locked"
        )
    )

    if (
        state.get(
            "screen"
        ) is None
        and event_screen
        in (
            "on",
            "off"
        )
    ):
        state[
            "screen"
        ] = event_screen

    if (
        state.get(
            "locked"
        ) is None
        and isinstance(
            event_locked,
            bool
        )
    ):
        state[
            "locked"
        ] = event_locked


def _phone_is_active(
    state
):
    """
    用于估算 foreground App 时长。

    明确屏幕关闭：
        inactive

    明确锁定：
        inactive

    其他情况：
        只要有 foreground app，
        暂时视为 active。

    这样可以兼容历史记录里
    screen / locked 状态不完整的情况。
    """

    if state.get(
        "screen"
    ) == "off":
        return False

    if state.get(
        "locked"
    ) is True:
        return False

    if not (
        state.get(
            "app_name"
        )
        or state.get(
            "app_package"
        )
    ):
        return False

    return True


def _screen_is_active(
    state
):
    return (
        state.get(
            "screen"
        ) == "on"
        and state.get(
            "locked"
        ) is not True
    )


# =========================
# App 使用时长估算
# =========================

def aggregate_app_usage(
    events,
    start_epoch,
    end_epoch
):
    """
    events 可以包含 start_epoch 之前的少量事件。

    这是故意的：
    如果 09:00 开始查询，
    08:58 已经打开 ChatGPT，
    我们仍然应该知道
    09:00 时 foreground app 是 ChatGPT。

    所有时长都会裁切到：
    [start_epoch, end_epoch]
    """

    usage = {}

    state = {
        "screen": None,
        "locked": None,
        "app_name": None,
        "app_package": None
    }

    # =========================
    # 先重放查询窗口之前的事件，
    # 用于恢复 start 时刻的状态
    # =========================

    for event in events:
        timestamp = (
            event[
                "event_time"
            ]
        )

        if timestamp >= start_epoch:
            break

        _apply_event_to_state(
            state,
            event
        )

    cursor = (
        start_epoch
    )

    # =========================
    # 窗口内事件
    # =========================

    for event in events:
        timestamp = (
            event[
                "event_time"
            ]
        )

        if timestamp < start_epoch:
            continue

        if timestamp > end_epoch:
            break

        timestamp = clamp(
            timestamp,
            start_epoch,
            end_epoch
        )

        interval = max(
            0,
            timestamp - cursor
        )

        if (
            interval > 0
            and _phone_is_active(
                state
            )
        ):
            _add_app_duration(
                usage,
                state.get(
                    "app_name"
                ),
                state.get(
                    "app_package"
                ),
                interval
            )

        _apply_event_to_state(
            state,
            event
        )

        cursor = (
            timestamp
        )

        if (
            event.get(
                "event_type"
            )
            == "app_changed"
        ):
            record = (
                _ensure_app_record(
                    usage,
                    event.get(
                        "app_name"
                    ),
                    event.get(
                        "app_package"
                    )
                )
            )

            if record is not None:
                record[
                    "switch_count"
                ] += 1

                event_at = (
                    event.get(
                        "event_at"
                    )
                )

                if (
                    record[
                        "first_seen_at"
                    ]
                    is None
                ):
                    record[
                        "first_seen_at"
                    ] = event_at

                record[
                    "last_seen_at"
                ] = event_at

    # =========================
    # 最后一个事件到窗口结束
    # =========================

    if cursor < end_epoch:
        interval = (
            end_epoch
            - cursor
        )

        if (
            interval > 0
            and _phone_is_active(
                state
            )
        ):
            _add_app_duration(
                usage,
                state.get(
                    "app_name"
                ),
                state.get(
                    "app_package"
                ),
                interval
            )

    result = []

    for record in usage.values():

        seconds = max(
            0.0,
            record[
                "approx_seconds"
            ]
        )

        item = {
            "app_name": (
                record[
                    "app_name"
                ]
            ),

            "package_name": (
                record[
                    "package_name"
                ]
            ),

            "approx_seconds": (
                round(
                    seconds
                )
            ),

            "approx_minutes": (
                round(
                    seconds / 60,
                    1
                )
            ),

            "switch_count": (
                record[
                    "switch_count"
                ]
            ),

            "first_seen_at": (
                record[
                    "first_seen_at"
                ]
            ),

            "last_seen_at": (
                record[
                    "last_seen_at"
                ]
            )
        }

        # 完全没有时长、也没有切换事件的
        # 不需要进入最终使用榜单。
        if (
            item[
                "approx_seconds"
            ] <= 0
            and item[
                "switch_count"
            ] <= 0
        ):
            continue

        result.append(
            item
        )

    result.sort(
        key=lambda item: (
            item[
                "approx_seconds"
            ],
            item[
                "switch_count"
            ]
        ),
        reverse=True
    )

    return result


# =========================
# 屏幕活动聚合
# =========================

def aggregate_screen_activity(
    events,
    start_epoch,
    end_epoch
):
    state = {
        "screen": None,
        "locked": None,
        "app_name": None,
        "app_package": None
    }

    for event in events:
        timestamp = (
            event[
                "event_time"
            ]
        )

        if timestamp >= start_epoch:
            break

        _apply_event_to_state(
            state,
            event
        )

    cursor = (
        start_epoch
    )

    active_seconds = 0

    screen_on_count = 0
    screen_off_count = 0
    lock_count = 0
    unlock_count = 0

    for event in events:
        timestamp = (
            event[
                "event_time"
            ]
        )

        if timestamp < start_epoch:
            continue

        if timestamp > end_epoch:
            break

        timestamp = clamp(
            timestamp,
            start_epoch,
            end_epoch
        )

        interval = max(
            0,
            timestamp - cursor
        )

        if (
            interval > 0
            and _screen_is_active(
                state
            )
        ):
            active_seconds += (
                interval
            )

        event_type = (
            event.get(
                "event_type"
            )
        )

        if event_type == "screen_on":
            screen_on_count += 1

        elif event_type == "screen_off":
            screen_off_count += 1

        elif event_type == "lock":
            lock_count += 1

        elif event_type == "unlock":
            unlock_count += 1

        _apply_event_to_state(
            state,
            event
        )

        cursor = (
            timestamp
        )

    if cursor < end_epoch:
        interval = (
            end_epoch
            - cursor
        )

        if (
            interval > 0
            and _screen_is_active(
                state
            )
        ):
            active_seconds += (
                interval
            )

    return {
        "active_seconds": (
            round(
                active_seconds
            )
        ),

        "active_minutes": (
            round(
                active_seconds
                / 60,
                1
            )
        ),

        "screen_on_count": (
            screen_on_count
        ),

        "screen_off_count": (
            screen_off_count
        ),

        "lock_count": (
            lock_count
        ),

        "unlock_count": (
            unlock_count
        )
    }


# =========================
# Event 统计
# =========================

def aggregate_event_counts(
    events,
    start_epoch,
    end_epoch
):
    counts = {
        "total": 0,
        "app_changed": 0,
        "screen_on": 0,
        "screen_off": 0,
        "lock": 0,
        "unlock": 0,
        "interaction": 0,
        "initial": 0
    }

    for event in events:
        timestamp = (
            event[
                "event_time"
            ]
        )

        if timestamp < start_epoch:
            continue

        if timestamp > end_epoch:
            break

        event_type = (
            event.get(
                "event_type"
            )
        )

        counts[
            "total"
        ] += 1

        if event_type in counts:
            counts[
                event_type
            ] += 1

    return counts


# =========================
# Timeline 输出
# =========================

def build_filtered_timeline(
    events,
    start_epoch,
    end_epoch,
    selected_types,
    limit=200
):
    try:
        limit = int(
            limit
        )

    except Exception:
        limit = 200

    limit = max(
        1,
        min(
            limit,
            1000
        )
    )

    timeline = []

    for event in events:
        timestamp = (
            event[
                "event_time"
            ]
        )

        if timestamp < start_epoch:
            continue

        if timestamp > end_epoch:
            break

        category = (
            event.get(
                "category"
            )
        )

        if (
            category
            not in selected_types
        ):
            continue

        item = {
            "event": (
                event.get(
                    "event_type"
                )
            ),

            "at": (
                event.get(
                    "event_at"
                )
            )
        }

        if (
            event.get(
                "event_type"
            )
            == "app_changed"
        ):
            item[
                "app_name"
            ] = event.get(
                "app_name"
            )

            item[
                "package_name"
            ] = event.get(
                "app_package"
            )

        if category == "screen":

            screen = (
                event.get(
                    "screen"
                )
            )

            locked = (
                event.get(
                    "locked"
                )
            )

            if screen is not None:
                item[
                    "screen"
                ] = screen

            if locked is not None:
                item[
                    "locked"
                ] = locked

        timeline.append(
            item
        )

    # 保留最近 limit 条，
    # 但最终仍按时间正序返回。
    if len(
        timeline
    ) > limit:
        timeline = (
            timeline[
                -limit:
            ]
        )

    return timeline


# =========================
# 事实型人话摘要
# =========================

def _display_app_name(
    item
):
    app_name = (
        item.get(
            "app_name"
        )
    )

    if app_name:
        return str(
            app_name
        )

    package_name = (
        item.get(
            "package_name"
        )
    )

    if package_name:
        return str(
            package_name
        )

    return "未知应用"


def build_factual_summary(
    app_usage,
    screen_activity,
    event_counts,
    selected_types
):
    parts = []

    # =========================
    # Apps
    # =========================

    if "apps" in selected_types:

        meaningful_apps = [
            item
            for item
            in app_usage
            if (
                item.get(
                    "approx_seconds",
                    0
                ) > 0
                or item.get(
                    "switch_count",
                    0
                ) > 0
            )
        ]

        if meaningful_apps:
            top_apps = (
                meaningful_apps[:3]
            )

            app_parts = []

            for item in top_apps:
                name = (
                    _display_app_name(
                        item
                    )
                )

                minutes = (
                    item.get(
                        "approx_minutes",
                        0
                    )
                )

                if minutes >= 1:
                    app_parts.append(
                        f"{name}约"
                        f"{round(minutes)}分钟"
                    )

                else:
                    app_parts.append(
                        f"{name}短暂使用"
                    )

            if app_parts:
                parts.append(
                    "手机活动主要集中在"
                    + "、".join(
                        app_parts
                    )
                )

            app_switches = (
                event_counts.get(
                    "app_changed",
                    0
                )
            )

            if app_switches > 1:
                parts.append(
                    f"记录到约"
                    f"{app_switches}次应用切换"
                )

        else:
            parts.append(
                "这段时间没有记录到明显的应用切换活动"
            )

    # =========================
    # Screen
    # =========================

    if "screen" in selected_types:

        active_minutes = (
            screen_activity.get(
                "active_minutes"
            )
        )

        screen_on_count = (
            screen_activity.get(
                "screen_on_count",
                0
            )
        )

        unlock_count = (
            screen_activity.get(
                "unlock_count",
                0
            )
        )

        if (
            isinstance(
                active_minutes,
                (int, float)
            )
            and active_minutes > 0
        ):
            parts.append(
                f"屏幕解锁活跃时间约"
                f"{round(active_minutes)}分钟"
            )

        if screen_on_count > 0:
            parts.append(
                f"记录到"
                f"{screen_on_count}次亮屏"
            )

        if unlock_count > 0:
            parts.append(
                f"记录到"
                f"{unlock_count}次解锁"
            )

    # =========================
    # Interaction
    # =========================

    if "interaction" in selected_types:

        interactions = (
            event_counts.get(
                "interaction",
                0
            )
        )

        if interactions > 0:
            parts.append(
                f"记录到"
                f"{interactions}次交互更新"
            )

    if not parts:
        return (
            "这个时间段内没有足够的手机活动记录可供总结。"
        )

    return (
        "；".join(
            parts
        )
        + "。"
    )


# =========================
# 完整 Short-term History
# =========================

def build_phone_history_summary(
    events,
    start_epoch,
    end_epoch,
    types=None,
    include_timeline=False,
    timeline_limit=200
):
    """
    Short-term History 2.0 主入口。

    参数：

    events:
        phone_activity_events 列表。

        最好包含 start_epoch 之前
        至少一条历史事件，
        用来恢复窗口开始时的
        App / screen / lock 状态。

    start_epoch:
        查询窗口开始 UTC epoch seconds。

    end_epoch:
        查询窗口结束 UTC epoch seconds。

    types:
        None
        "all"
        "apps"
        "apps,screen"
        ["apps", "screen"]

    include_timeline:
        是否返回筛选后的原始 timeline。

    timeline_limit:
        timeline 最大返回数量。

    返回：
        纯事实结构化摘要。
    """

    start_epoch = (
        _safe_int(
            start_epoch
        )
    )

    end_epoch = (
        _safe_int(
            end_epoch
        )
    )

    if (
        start_epoch is None
        or end_epoch is None
    ):
        return {
            "available": False,
            "reason": (
                "invalid_time_range"
            )
        }

    if end_epoch <= start_epoch:
        return {
            "available": False,
            "reason": (
                "invalid_time_range"
            )
        }

    selected_types = (
        parse_history_types(
            types
        )
    )

    normalized = (
        normalize_events(
            events
        )
    )

    # =========================
    # 是否有窗口内数据
    # =========================

    window_events = [
        event
        for event
        in normalized
        if (
            start_epoch
            <= event[
                "event_time"
            ]
            <= end_epoch
        )
    ]

    app_usage = (
        aggregate_app_usage(
            normalized,
            start_epoch,
            end_epoch
        )
    )

    screen_activity = (
        aggregate_screen_activity(
            normalized,
            start_epoch,
            end_epoch
        )
    )

    event_counts = (
        aggregate_event_counts(
            normalized,
            start_epoch,
            end_epoch
        )
    )

    # =========================
    # dominant apps
    # =========================

    dominant_apps = []

    for item in app_usage[:5]:
        dominant_apps.append({
            "app_name": (
                item.get(
                    "app_name"
                )
            ),

            "package_name": (
                item.get(
                    "package_name"
                )
            ),

            "approx_minutes": (
                item.get(
                    "approx_minutes"
                )
            )
        })

    summary = (
        build_factual_summary(
            app_usage,
            screen_activity,
            event_counts,
            selected_types
        )
    )

    result = {
        "available": True,

        "period": {
            "start": (
                epoch_to_iso(
                    start_epoch
                )
            ),

            "end": (
                epoch_to_iso(
                    end_epoch
                )
            ),

            "duration_seconds": (
                end_epoch
                - start_epoch
            ),

            "duration_minutes": (
                round(
                    (
                        end_epoch
                        - start_epoch
                    )
                    / 60,
                    1
                )
            )
        },

        "selected_types": (
            sorted(
                selected_types
            )
        ),

        "record_count": (
            len(
                window_events
            )
        ),

        "factual_summary": (
            summary
        )
    }

    # =========================
    # Apps
    # =========================

    if "apps" in selected_types:

        result[
            "app_usage"
        ] = app_usage

        result[
            "dominant_apps"
        ] = dominant_apps

        result[
            "app_switch_count"
        ] = (
            event_counts.get(
                "app_changed",
                0
            )
        )

    # =========================
    # Screen
    # =========================

    if "screen" in selected_types:

        result[
            "screen_activity"
        ] = (
            screen_activity
        )

    # =========================
    # Interaction
    # =========================

    if (
        "interaction"
        in selected_types
    ):
        result[
            "interaction_count"
        ] = (
            event_counts.get(
                "interaction",
                0
            )
        )

    # =========================
    # 通用 Event counts
    # =========================

    result[
        "event_counts"
    ] = {
        key: value
        for (
            key,
            value
        ) in (
            event_counts.items()
        )
        if (
            key == "total"
            or (
                event_category(
                    key
                )
                in selected_types
            )
        )
    }

    # =========================
    # Timeline
    # =========================

    if include_timeline:

        result[
            "timeline"
        ] = (
            build_filtered_timeline(
                normalized,
                start_epoch,
                end_epoch,
                selected_types,
                limit=timeline_limit
            )
        )

    # =========================
    # 数据覆盖范围
    # =========================

    if window_events:

        result[
            "data_coverage"
        ] = {
            "first_event_at": (
                window_events[
                    0
                ].get(
                    "event_at"
                )
            ),

            "last_event_at": (
                window_events[
                    -1
                ].get(
                    "event_at"
                )
            ),

            "has_events": True
        }

    else:

        result[
            "data_coverage"
        ] = {
            "first_event_at": None,
            "last_event_at": None,
            "has_events": False
        }

    return result
