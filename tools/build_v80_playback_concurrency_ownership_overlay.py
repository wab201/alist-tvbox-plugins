"""Apply the P5-5E playback concurrency ownership fixes."""

import ast
import hashlib


OVERLAY_ALIAS_ZH = "播放并发所有权覆盖层"
EXPECTED_INPUT_SIZE = 857478
EXPECTED_INPUT_SHA256 = (
    "1BC3509C37DCB550F39A4324A2A17B4834029FFD6096C4366C46F05247B16DBA"
)


class PlaybackConcurrencyOwnershipOverlayError(RuntimeError):
    pass


SOURCE_SWITCH_ANCHOR = '''        if force_route_refresh:
            self._invalidate_route_probe(
                parsed.get("url"),
                parsed.get("resourceId"),
                parsed.get("resourceMode") or "vod",
            )
'''


SOURCE_SWITCH_REPLACEMENT = '''        if force_route_refresh:
            self._invalidate_route_probe(
                parsed.get("url"),
                parsed.get("resourceId"),
                parsed.get("resourceMode") or "vod",
                expected_generation=player_generation,
                expected_backend=player_backend,
            )
'''


INVALIDATE_ANCHOR = '''    def _invalidate_route_probe(self, target, resource_id="", resource_mode="vod"):
        """Remove one short-lived probe/signed-output entry before a source switch."""
        key = self._route_probe_key(target, resource_id, resource_mode)
        if not key:
            return False
        with self._cache_lock:
            removed = self._route_probe_cache.pop(key, None) is not None
        return removed
'''


INVALIDATE_REPLACEMENT = '''    def _invalidate_route_probe(
            self, target, resource_id="", resource_mode="vod",
            expected_generation=None, expected_backend=None):
        """Remove one short-lived probe/signed-output entry before a source switch."""
        key = self._route_probe_key(
            target, resource_id, resource_mode, backend=expected_backend,
        )
        if not key:
            return False
        with self._cache_lock:
            if (
                    expected_generation is not None
                    and expected_generation != self._cache_generation):
                return False
            if (
                    expected_backend is not None
                    and expected_backend != self._resource_capability_identity()):
                return False
            removed = self._route_probe_cache.pop(key, None) is not None
        return removed
'''


ROUTE_SAVE_OWNER_ANCHOR = '''    def _schedule_route_quality_save(self):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        job_owner = object()
        with self._cache_lock:
            self._route_quality_dirty = True
            if self._route_quality_saving:
                return True
            self._route_quality_saving = job_owner
            generation = self._cache_generation
'''


ROUTE_SAVE_OWNER_REPLACEMENT = '''    def _schedule_route_quality_save(
            self, expected_generation=None, expected_backend=None):
        setter = getattr(self, "setCache", None)
        if not callable(setter):
            return False
        job_owner = object()
        with self._cache_lock:
            if (
                    expected_generation is not None
                    and expected_generation != self._cache_generation):
                return False
            if (
                    expected_backend is not None
                    and expected_backend != self._resource_capability_identity()):
                return False
            self._route_quality_dirty = True
            if self._route_quality_saving:
                return True
            self._route_quality_saving = job_owner
            generation = self._cache_generation
            backend = self._resource_capability_identity()
'''


ROUTE_SAVE_REPEAT_ANCHOR = '''            if repeat:
                self._schedule_route_quality_save()
'''


ROUTE_SAVE_REPEAT_REPLACEMENT = '''            if repeat:
                self._schedule_route_quality_save(
                    expected_generation=generation, expected_backend=backend,
                )
'''


ROUTE_RECORD_SCHEDULE_ANCHOR = '''    def _record_route_quality(self, play_id, success, startup_ms=0, signals=None,
                              expected_generation=None, expected_backend=None):
        key = self._route_quality_key(play_id)
        if not key:
            return
        self._load_route_quality_history()
        signals = signals if isinstance(signals, dict) else {}
        with self._cache_lock:
            if (
                    expected_generation is not None
                    and expected_generation != self._cache_generation):
                return
            if (
                    expected_backend is not None
                    and expected_backend != self._resource_capability_identity()):
                return
            record = dict(self._route_quality_history.get(key) or {})
            successes = self._positive_int(record.get("successes"), 0)
            failures = self._positive_int(record.get("failures"), 0)
            if successes + failures >= 50:
                successes //= 2
                failures //= 2
            if success:
                successes += 1
            else:
                failures += 1
            record["successes"] = successes
            record["failures"] = failures
            startup = self._positive_int(startup_ms or signals.get("startup_ms"), 0)
            if success and startup:
                timed = self._positive_int(record.get("timedSuccesses"), 0)
                average = self._positive_int(record.get("avgStartupMs"), 0)
                record["avgStartupMs"] = int(round((average * timed + startup) / float(timed + 1)))
                record["timedSuccesses"] = min(50, timed + 1)
            codec = str(signals.get("codec") or "").strip().lower()
            if codec:
                record["codec"] = codec
            height = self._positive_int(signals.get("height"), 0)
            if height:
                record["height"] = height
            if isinstance(signals.get("subtitle"), bool):
                record["subtitle"] = signals.get("subtitle")
            record["updatedAt"] = int(time.time())
            self._route_quality_history[key] = record
            if len(self._route_quality_history) > self.ROUTE_QUALITY_LIMIT * 2:
                oldest = sorted(
                    self._route_quality_history,
                    key=lambda item: self._positive_int(self._route_quality_history[item].get("updatedAt"), 0),
                )[:self.ROUTE_QUALITY_LIMIT]
                for item in oldest:
                    self._route_quality_history.pop(item, None)
        self._schedule_route_quality_save()

    @staticmethod
    def _media_quality_signals(text="", content_type="", sample=b""):
'''


ROUTE_RECORD_SCHEDULE_REPLACEMENT = '''    def _record_route_quality(self, play_id, success, startup_ms=0, signals=None,
                              expected_generation=None, expected_backend=None):
        signals = signals if isinstance(signals, dict) else {}
        with self._history_context_lock:
            with self._cache_lock:
                if (
                        expected_generation is not None
                        and expected_generation != self._cache_generation):
                    return
                if (
                        expected_backend is not None
                        and expected_backend != self._resource_capability_identity()):
                    return
            key = self._route_quality_key(play_id)
            if not key:
                return
            self._load_route_quality_history()
        with self._cache_lock:
            if (
                    expected_generation is not None
                    and expected_generation != self._cache_generation):
                return
            if (
                    expected_backend is not None
                    and expected_backend != self._resource_capability_identity()):
                return
            record = dict(self._route_quality_history.get(key) or {})
            successes = self._positive_int(record.get("successes"), 0)
            failures = self._positive_int(record.get("failures"), 0)
            if successes + failures >= 50:
                successes //= 2
                failures //= 2
            if success:
                successes += 1
            else:
                failures += 1
            record["successes"] = successes
            record["failures"] = failures
            startup = self._positive_int(startup_ms or signals.get("startup_ms"), 0)
            if success and startup:
                timed = self._positive_int(record.get("timedSuccesses"), 0)
                average = self._positive_int(record.get("avgStartupMs"), 0)
                record["avgStartupMs"] = int(round((average * timed + startup) / float(timed + 1)))
                record["timedSuccesses"] = min(50, timed + 1)
            codec = str(signals.get("codec") or "").strip().lower()
            if codec:
                record["codec"] = codec
            height = self._positive_int(signals.get("height"), 0)
            if height:
                record["height"] = height
            if isinstance(signals.get("subtitle"), bool):
                record["subtitle"] = signals.get("subtitle")
            record["updatedAt"] = int(time.time())
            self._route_quality_history[key] = record
            if len(self._route_quality_history) > self.ROUTE_QUALITY_LIMIT * 2:
                oldest = sorted(
                    self._route_quality_history,
                    key=lambda item: self._positive_int(self._route_quality_history[item].get("updatedAt"), 0),
                )[:self.ROUTE_QUALITY_LIMIT]
                for item in oldest:
                    self._route_quality_history.pop(item, None)
        self._schedule_route_quality_save(
            expected_generation=expected_generation,
            expected_backend=expected_backend,
        )

    @staticmethod
    def _media_quality_signals(text="", content_type="", sample=b""):
'''


PLAYER_SIDE_EFFECTS_ANCHOR = '''                self._inject_resume(output, effective)
                self._record_route_quality(
                    quality_id, True,
                    startup_ms=(quality_probe or {}).get("startup_ms"),
                    signals=quality_probe,
                    expected_generation=player_generation,
                    expected_backend=player_backend,
                )
'''


PLAYER_SIDE_EFFECTS_REPLACEMENT = '''                with self._history_context_lock:
                    with self._cache_lock:
                        if (
                                player_generation != self._cache_generation
                                or player_backend != self._resource_capability_identity()):
                            raise ReliabilityFailure("cancelled", operation="player")
                    self._timeout_budget_controller.current().checkpoint()
                    self._inject_resume(output, effective)
                self._record_route_quality(
                    quality_id, True,
                    startup_ms=(quality_probe or {}).get("startup_ms"),
                    signals=quality_probe,
                    expected_generation=player_generation,
                    expected_backend=player_backend,
                )
'''


PLAYER_FINALIZE_ANCHOR = '''                with self._history_context_lock:
                    with self._cache_lock:
                        player_is_current = (
                            player_generation == self._cache_generation
                            and player_backend == self._resource_capability_identity()
                        )
                if player_is_current:
                    self._register_playback_sync_window(effective)
                    self._schedule_native_history_ui_refresh()
                return output
'''


PLAYER_FINALIZE_REPLACEMENT = '''                with self._history_context_lock:
                    with self._cache_lock:
                        if (
                                player_generation != self._cache_generation
                                or player_backend != self._resource_capability_identity()):
                            raise ReliabilityFailure("cancelled", operation="player")
                    self._timeout_budget_controller.current().checkpoint()
                    self._register_playback_sync_window(effective)
                    self._schedule_native_history_ui_refresh()
                    return output
'''


INSERTIONS = (
    ("source-switch-generation", SOURCE_SWITCH_ANCHOR, SOURCE_SWITCH_REPLACEMENT),
    ("source-switch-invalidation-owner", INVALIDATE_ANCHOR, INVALIDATE_REPLACEMENT),
    ("route-quality-save-owner", ROUTE_SAVE_OWNER_ANCHOR, ROUTE_SAVE_OWNER_REPLACEMENT),
    ("route-quality-repeat-generation", ROUTE_SAVE_REPEAT_ANCHOR, ROUTE_SAVE_REPEAT_REPLACEMENT),
    ("route-quality-record-generation", ROUTE_RECORD_SCHEDULE_ANCHOR, ROUTE_RECORD_SCHEDULE_REPLACEMENT),
    ("player-resume-generation", PLAYER_SIDE_EFFECTS_ANCHOR, PLAYER_SIDE_EFFECTS_REPLACEMENT),
    ("player-finalize-generation", PLAYER_FINALIZE_ANCHOR, PLAYER_FINALIZE_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise PlaybackConcurrencyOwnershipOverlayError(
            "playback concurrency anchor %s must appear once, found %d" % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _spider(tree):
    classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(classes) != 1:
        raise PlaybackConcurrencyOwnershipOverlayError("expected one Spider class")
    return classes[0]


def _method(spider, name):
    methods = [
        node for node in spider.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(methods) != 1:
        raise PlaybackConcurrencyOwnershipOverlayError(
            "expected one Spider.%s method" % name
        )
    return methods[0]


def _call_name(node):
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _calls(method, name):
    return [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call) and _call_name(node) == name
    ]


def _has_keyword(call, name):
    return any(keyword.arg == name for keyword in call.keywords)


def _with_owns_lock(node, lock_name):
    if not isinstance(node, ast.With):
        return False
    for item in node.items:
        expression = item.context_expr
        if (
                isinstance(expression, ast.Attribute)
                and isinstance(expression.value, ast.Name)
                and expression.value.id == "self"
                and expression.attr == lock_name):
            return True
    return False


def _calls_under_lock(method, call_name, lock_name):
    found = []

    def visit(node, owned):
        current_owned = owned or _with_owns_lock(node, lock_name)
        if isinstance(node, ast.Call) and _call_name(node) == call_name:
            found.append(current_owned)
        for child in ast.iter_child_nodes(node):
            visit(child, current_owned)

    visit(method, False)
    return found


def _audit_output(input_tree, output_tree):
    input_spider = _spider(input_tree)
    output_spider = _spider(output_tree)
    for unchanged in (
            "_atvp_play", "_v80_atvp_play_unbounded",
            "_probe_media_output", "_v80_probe_media_output_unbounded",
            "_resolve_addresses", "_pinned_media_request",
            "_resource_api_get", "_resource_candidates"):
        if ast.dump(_method(input_spider, unchanged)) != ast.dump(
                _method(output_spider, unchanged)):
            raise PlaybackConcurrencyOwnershipOverlayError(
                "%s must remain unchanged" % unchanged
            )

    player = _method(output_spider, "_v80_playerContent_unbounded")
    invalidate_calls = _calls(player, "_invalidate_route_probe")
    if not (
            len(invalidate_calls) == 1
            and _has_keyword(invalidate_calls[0], "expected_generation")
            and _has_keyword(invalidate_calls[0], "expected_backend")):
        raise PlaybackConcurrencyOwnershipOverlayError(
            "player source switch must pass generation and backend"
        )
    for call_name in ("_inject_resume", "_register_playback_sync_window"):
        ownership = _calls_under_lock(player, call_name, "_history_context_lock")
        if ownership != [True]:
            raise PlaybackConcurrencyOwnershipOverlayError(
                "%s must have one history-context owner" % call_name
            )

    invalidator = _method(output_spider, "_invalidate_route_probe")
    invalidator_args = [argument.arg for argument in invalidator.args.args]
    if not {"expected_generation", "expected_backend"}.issubset(invalidator_args):
        raise PlaybackConcurrencyOwnershipOverlayError(
            "route invalidation must accept generation and backend"
        )

    schedule = _method(output_spider, "_schedule_route_quality_save")
    schedule_args = [argument.arg for argument in schedule.args.args]
    if not {"expected_generation", "expected_backend"}.issubset(schedule_args):
        raise PlaybackConcurrencyOwnershipOverlayError(
            "route-quality save must accept generation and backend"
        )
    repeat_calls = _calls(schedule, "_schedule_route_quality_save")
    if not (
            len(repeat_calls) == 1
            and _has_keyword(repeat_calls[0], "expected_generation")
            and _has_keyword(repeat_calls[0], "expected_backend")):
        raise PlaybackConcurrencyOwnershipOverlayError(
            "route-quality repeat must preserve generation and backend"
        )
    recorder = _method(output_spider, "_record_route_quality")
    load_ownership = _calls_under_lock(
        recorder, "_load_route_quality_history", "_history_context_lock",
    )
    if load_ownership != [True]:
        raise PlaybackConcurrencyOwnershipOverlayError(
            "route-quality lazy load must have one history-context owner"
        )
    record_calls = _calls(recorder, "_schedule_route_quality_save")
    if not (
            len(record_calls) == 1
            and _has_keyword(record_calls[0], "expected_generation")
            and _has_keyword(record_calls[0], "expected_backend")):
        raise PlaybackConcurrencyOwnershipOverlayError(
            "route-quality record must preserve generation and backend"
        )


def apply_playback_concurrency_ownership_overlay(source):
    try:
        raw = bytes(source)
        text = raw.decode("utf-8")
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise PlaybackConcurrencyOwnershipOverlayError(
            "playback concurrency input is not valid UTF-8 bytes"
        ) from exc
    input_sha256 = hashlib.sha256(raw).hexdigest().upper()
    if len(raw) != EXPECTED_INPUT_SIZE or input_sha256 != EXPECTED_INPUT_SHA256:
        raise PlaybackConcurrencyOwnershipOverlayError(
            "playback concurrency input does not match the P5-5D candidate"
        )
    output = text
    labels = []
    for label, anchor, replacement in INSERTIONS:
        output = _replace_once(output, anchor, replacement, label)
        labels.append(label)
    try:
        input_tree = ast.parse(text)
        output_tree = ast.parse(output)
    except SyntaxError as exc:
        raise PlaybackConcurrencyOwnershipOverlayError(
            "playback concurrency overlay produced invalid Python: %s" % exc
        ) from exc
    _audit_output(input_tree, output_tree)
    data = output.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "input_size": len(raw),
        "input_sha256": input_sha256,
        "alias_zh": OVERLAY_ALIAS_ZH,
        "insertions": tuple(labels),
    }
