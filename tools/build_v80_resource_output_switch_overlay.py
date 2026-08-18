"""Apply the private V80 layered-resource output switch to the final candidate."""

import ast
import hashlib


ALIAS_ZH = "P2 私有 V80 资源输出受控切换覆盖层"
EXPECTED_INPUT_SIZE = 865875
EXPECTED_INPUT_SHA256 = (
    "DCD2CE50277119998BE2D92631CC90C11B3DDC733CB7B397E072E62FE117E773"
)


class ResourceOutputSwitchOverlayError(RuntimeError):
    """Raised when the fixed private-V80 output switch cannot be applied."""


STATE_ANCHOR = '''        self._resource_search_layered_shadow_last_report = None
        self._validated_resource_details = OrderedDict()
'''
STATE_REPLACEMENT = '''        self._resource_search_layered_shadow_last_report = None
        self._v80_resource_layered_output_enabled = False
        self._validated_resource_details = OrderedDict()
'''

INIT_ANCHOR = '''        self.atvp_plugin_mode = self._first(config, "atvp_plugin_mode", "runtime_mode", "runtime").strip().lower()
        self._alist_tvbox_plugin = self.atvp_plugin_mode == self.ATVP_PLUGIN_MODE
        self.atvp_api = self._http_base(config.get("atvp_api") or config.get("_atvp_api") or config.get("api"), "")
'''
INIT_REPLACEMENT = '''        self.atvp_plugin_mode = self._first(config, "atvp_plugin_mode", "runtime_mode", "runtime").strip().lower()
        self._alist_tvbox_plugin = self.atvp_plugin_mode == self.ATVP_PLUGIN_MODE
        self._v80_resource_layered_output_enabled = (
            self._resource_layered_output_from_config(config)
        )
        self.atvp_api = self._http_base(config.get("atvp_api") or config.get("_atvp_api") or config.get("api"), "")
'''

HELPER_ANCHOR = '''    def _resource_candidates(
            self, item, deadline=None, background=False,
            expected_generation=None):
'''
HELPER_REPLACEMENT = '''    def _resource_layered_output_active(self):
        return self._v80_resource_layered_output_enabled is True

    def _resource_layered_output_from_config(self, config):
        return bool(
            self._alist_tvbox_plugin
            and self._bool_value(config.get("v80_resource_layered_output"), False)
        )

    def _resource_binding_resource_id(self, item):
        binding_keys = [str(item.get("tmdb_id") or ""), str(item.get("source_id") or "")]
        for key in binding_keys:
            if key and str(self.follow_alist_bindings.get(key) or "").strip():
                return str(self.follow_alist_bindings.get(key)).strip()
        return str(item.get("alist_vod_id") or "").strip()

    def _resource_recent_resource_id(self, item):
        recent_route = (
            item.get("last_play_route")
            if isinstance(item.get("last_play_route"), dict) else {}
        )
        if not recent_route:
            return ""
        recent_backend = str(recent_route.get("backend") or "")
        if recent_backend and recent_backend != self._resource_capability_identity():
            return ""
        return str(recent_route.get("resourceId") or "").strip()

    def _resource_output_provider(self, row):
        return self._resource_provider_key(
            row.get("provider"), row.get("type"), row.get("type_name"),
            row.get("vod_remarks"), row.get("source"),
            row.get("vod_id") or row.get("id") or row.get("url"),
        )

    def _resource_output_shadow_report(self, legacy_rows, candidate_rows):
        legacy_count = 0
        candidate_count = 0
        try:
            legacy = list(legacy_rows or ())
            candidate = list(candidate_rows or ())
            legacy_count = len(legacy)
            candidate_count = len(candidate)
            common_count = min(legacy_count, candidate_count)
            first_difference = next((
                index for index in range(common_count)
                if legacy[index] != candidate[index]
            ), -1)
            if first_difference < 0 and legacy_count != candidate_count:
                first_difference = common_count
            return {
                "status": "equal" if first_difference < 0 else "different",
                "legacy_count": legacy_count,
                "candidate_count": candidate_count,
                "first_difference": first_difference,
                "error_type": "",
            }
        except Exception as exc:
            return {
                "status": "error",
                "legacy_count": legacy_count,
                "candidate_count": candidate_count,
                "first_difference": -1,
                "error_type": type(exc).__name__,
            }

    def _resource_output_candidate_order(
            self, rows, item, bound="", cached_rows=(), modes=None,
            legacy_bound=None):
        mode_order = tuple(modes or self.RESOURCE_SEARCH_MODES)
        legacy_order_bound = bound if legacy_bound is None else legacy_bound
        if self._resource_layered_output_active():
            try:
                return combine_v70_layered_resource_rows(
                    rows,
                    merge_rows=lambda left, right: self._merge_resource_rows(
                        left, right, item, bound,
                    ),
                    score_row=lambda row: self._resource_score(row, item, bound),
                    preference_row=lambda row: self._resource_row_preference(
                        row, item, bound,
                    ),
                    provider_row=self._resource_output_provider,
                    cached_rows=cached_rows,
                    recent_resource_id=self._resource_recent_resource_id(item),
                    binding_resource_id=bound,
                    available_modes=mode_order,
                    modes=mode_order,
                )
            except Exception:
                pass
        return self._resource_fair_candidate_order(
            rows, item, bound=legacy_order_bound, modes=mode_order,
        )

    def _resource_candidates(
            self, item, deadline=None, background=False,
            expected_generation=None):
'''

BOUND_ANCHOR = '''        binding_keys = [str(item.get("tmdb_id") or ""), str(item.get("source_id") or "")]
        bound = ""
        for key in binding_keys:
            if key and str(self.follow_alist_bindings.get(key) or "").strip():
                bound = str(self.follow_alist_bindings.get(key)).strip()
                break
        if not bound:
            bound = str(item.get("alist_vod_id") or "").strip()
'''
BOUND_REPLACEMENT = '''        bound = self._resource_binding_resource_id(item)
'''

RECENT_ANCHOR = '''                recent_resource_id = ""
                recent_route = item.get("last_play_route") if isinstance(item.get("last_play_route"), dict) else {}
                if recent_route:
                    recent_backend = str(recent_route.get("backend") or "")
                    if not recent_backend or recent_backend == self._resource_capability_identity():
                        recent_resource_id = str(recent_route.get("resourceId") or "").strip()
'''
RECENT_REPLACEMENT = '''                recent_resource_id = self._resource_recent_resource_id(item)
'''

FOREGROUND_ORDER_ANCHOR = '''        ordered = self._resource_fair_candidate_order(
            rows,
            item,
            bound=bound,
            modes=sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)),
        )
'''
FOREGROUND_ORDER_REPLACEMENT = '''        ordered = self._resource_output_candidate_order(
            rows,
            item,
            bound=bound,
            cached_rows=cached_rows if supplement_modes else (),
            modes=sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)),
        )
'''

BACKGROUND_ORDER_ANCHOR = '''                shadow_rows = (
                    candidates if self._resource_candidate_shadow_enabled else None
                )
                shadow_modes = tuple(sorted(
                    modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99),
                ))
                candidates = self._resource_fair_candidate_order(
                    candidates, item, modes=shadow_modes,
                )
'''
BACKGROUND_ORDER_REPLACEMENT = '''                raw_candidates = candidates
                shadow_rows = (
                    raw_candidates if self._resource_candidate_shadow_enabled else None
                )
                shadow_modes = tuple(sorted(
                    modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99),
                ))
                legacy_candidates = None
                if shadow_rows is not None and self._resource_layered_output_active():
                    legacy_candidates = self._resource_fair_candidate_order(
                        raw_candidates, item, modes=shadow_modes,
                    )
                candidates = self._resource_output_candidate_order(
                    raw_candidates,
                    item,
                    bound=self._resource_binding_resource_id(item),
                    modes=shadow_modes,
                    legacy_bound="",
                )
'''

SHADOW_PAYLOAD_ANCHOR = '''                        shadow_payload = (
                            candidates,
                            shadow_rows,
                            shadow_modes,
                        )
'''
SHADOW_PAYLOAD_REPLACEMENT = '''                        shadow_payload = (
                            legacy_candidates if legacy_candidates is not None else candidates,
                            shadow_rows,
                            shadow_modes,
                            candidates if self._resource_layered_output_active() else None,
                        )
'''

SHADOW_CALL_ANCHOR = '''                    legacy_rows, shadow_rows, shadow_modes = shadow_payload
                    run_background_resource_candidate_shadow(
                        self, legacy_rows, shadow_rows, item=item,
                        cache_key=cache_key, generation=generation, modes=shadow_modes,
                    )
'''
SHADOW_CALL_REPLACEMENT = '''                    legacy_rows, shadow_rows, shadow_modes, candidate_rows = shadow_payload
                    shadow_result = run_background_resource_candidate_shadow(
                        self, legacy_rows, shadow_rows, item=item,
                        cache_key=cache_key, generation=generation, modes=shadow_modes,
                    )
                    if (
                            candidate_rows is not None
                            and shadow_result is not None
                            and shadow_result["decision"]["run"]):
                        production_report = self._resource_output_shadow_report(
                            legacy_rows, candidate_rows,
                        )
                        shadow_result["report"] = production_report
                        with self._cache_lock:
                            if generation == self._cache_generation:
                                self._resource_candidate_shadow_last_report = production_report
'''

INSERTIONS = (
    ("controlled-switch-state", STATE_ANCHOR, STATE_REPLACEMENT),
    ("private-raw-plugin-config", INIT_ANCHOR, INIT_REPLACEMENT),
    ("shared-output-owner", HELPER_ANCHOR, HELPER_REPLACEMENT),
    ("shared-binding-owner", BOUND_ANCHOR, BOUND_REPLACEMENT),
    ("shared-recent-owner", RECENT_ANCHOR, RECENT_REPLACEMENT),
    ("foreground-production-owner", FOREGROUND_ORDER_ANCHOR, FOREGROUND_ORDER_REPLACEMENT),
    ("background-production-owner", BACKGROUND_ORDER_ANCHOR, BACKGROUND_ORDER_REPLACEMENT),
    ("background-shadow-legacy-owner", SHADOW_PAYLOAD_ANCHOR, SHADOW_PAYLOAD_REPLACEMENT),
    ("background-shadow-candidate-owner", SHADOW_CALL_ANCHOR, SHADOW_CALL_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise ResourceOutputSwitchOverlayError(
            "resource output switch anchor %s must appear once, found %d"
            % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def _spider_method(tree, name):
    spiders = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(spiders) != 1:
        raise ResourceOutputSwitchOverlayError("expected one Spider class")
    methods = [
        node for node in spiders[0].body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(methods) != 1:
        raise ResourceOutputSwitchOverlayError(
            "expected one Spider.%s method" % name
        )
    return methods[0]


def _named_calls(node, name):
    return [
        item for item in ast.walk(node)
        if isinstance(item, ast.Call)
        and (
            (isinstance(item.func, ast.Name) and item.func.id == name)
            or (isinstance(item.func, ast.Attribute) and item.func.attr == name)
        )
    ]


def _audit_output_switch(tree):
    init_method = _spider_method(tree, "_init_locked")
    config_method = _spider_method(tree, "_resource_layered_output_from_config")
    common_method = _spider_method(tree, "_resource_output_candidate_order")
    foreground_method = _spider_method(tree, "_resource_candidates")
    background_method = _spider_method(tree, "_schedule_supplement_resource_search")
    for name in (
        "_resource_layered_output_active",
        "_resource_binding_resource_id",
        "_resource_recent_resource_id",
        "_resource_output_provider",
        "_resource_output_shadow_report",
    ):
        _spider_method(tree, name)

    config_keys = [
        node for node in ast.walk(config_method)
        if isinstance(node, ast.Constant)
        and node.value == "v80_resource_layered_output"
    ]
    if len(config_keys) != 1:
        raise ResourceOutputSwitchOverlayError(
            "private V80 switch config must appear once"
        )
    if len(_named_calls(init_method, "_resource_layered_output_from_config")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "private V80 init must resolve the switch once"
        )
    if len(_named_calls(common_method, "combine_v70_layered_resource_rows")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "shared output owner must call the raw combiner once"
        )
    if len(_named_calls(common_method, "_resource_fair_candidate_order")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "shared output owner must keep one legacy fallback"
        )
    if len(_named_calls(foreground_method, "_resource_output_candidate_order")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "foreground output must use the shared owner once"
        )
    if _named_calls(foreground_method, "_resource_fair_candidate_order"):
        raise ResourceOutputSwitchOverlayError(
            "foreground output cannot bypass the shared owner"
        )
    if len(_named_calls(background_method, "_resource_output_candidate_order")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "background output must use the shared owner once"
        )
    if len(_named_calls(background_method, "_resource_fair_candidate_order")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "background may keep only the conditional legacy shadow baseline"
        )
    if len(_named_calls(background_method, "_resource_output_shadow_report")) != 1:
        raise ResourceOutputSwitchOverlayError(
            "background shadow must compare the actual production candidates once"
        )


def apply_resource_output_switch_overlay(source):
    input_bytes = bytes(source)
    if (
        len(input_bytes) != EXPECTED_INPUT_SIZE
        or hashlib.sha256(input_bytes).hexdigest().upper() != EXPECTED_INPUT_SHA256
    ):
        raise ResourceOutputSwitchOverlayError(
            "resource output switch input does not match the pinned V80 candidate"
        )
    try:
        text = input_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResourceOutputSwitchOverlayError(
            "resource output switch input is not valid UTF-8 bytes"
        ) from exc
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)
    try:
        tree = ast.parse(text, filename="build/v80-dev/resource-output-switch.py")
        compile(tree, "build/v80-dev/resource-output-switch.py", "exec")
    except SyntaxError as exc:
        raise ResourceOutputSwitchOverlayError(
            "resource output switch output is invalid: %s" % exc
        ) from exc
    _audit_output_switch(tree)

    output = text.encode("utf-8")
    return {
        "bytes": output,
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "size": len(output),
        "sha256": hashlib.sha256(output).hexdigest().upper(),
        "alias_zh": ALIAS_ZH,
        "insertions": tuple(label for label, _anchor, _replacement in INSERTIONS),
    }


def main():
    raise SystemExit(
        "import apply_resource_output_switch_overlay from the V80 build pipeline"
    )


if __name__ == "__main__":
    main()
