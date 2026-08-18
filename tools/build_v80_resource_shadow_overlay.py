"""Insert the fixed P2 background shadow call into the isolated V80 source."""

import ast
import hashlib


class RuntimeOverlayError(RuntimeError):
    """Raised when the fixed V80 runtime insertion cannot be applied exactly."""


STATE_ANCHOR = (
    "        self._resource_search_admissions = 0\n"
    "        self._validated_resource_details = OrderedDict()\n"
)
STATE_REPLACEMENT = (
    "        self._resource_search_admissions = 0\n"
    "        self._resource_candidate_shadow_lock = threading.Lock()\n"
    "        self._resource_candidate_shadow_enabled = False\n"
    "        self._resource_candidate_shadow_sample_every = 1\n"
    "        self._resource_candidate_shadow_budget_us = 0\n"
    "        self._resource_candidate_shadow_sampled_generation = None\n"
    "        self._resource_candidate_shadow_last_report = None\n"
    "        self._resource_search_layered_shadow_lock = threading.Lock()\n"
    "        self._resource_search_layered_shadow_enabled = False\n"
    "        self._resource_search_layered_shadow_sample_every = 1\n"
    "        self._resource_search_layered_shadow_budget_us = 0\n"
    "        self._resource_search_layered_shadow_sampled_generation = None\n"
    "        self._resource_search_layered_shadow_last_report = None\n"
    "        self._validated_resource_details = OrderedDict()\n"
)
RESET_ANCHOR = (
    "                self._route_quality_saving = None\n"
    "                self._cache_generation += 1\n"
    "                self._history_snapshot_revision += 1\n"
)
RESET_REPLACEMENT = (
    "                self._route_quality_saving = None\n"
    "                self._cache_generation += 1\n"
    "                self._resource_candidate_shadow_sampled_generation = None\n"
    "                self._resource_candidate_shadow_last_report = None\n"
    "                self._resource_search_layered_shadow_sampled_generation = None\n"
    "                self._resource_search_layered_shadow_last_report = None\n"
    "                self._history_snapshot_revision += 1\n"
)
DESTROY_ANCHOR = (
    "    def destroy(self):\n"
    "        with self._history_context_lock:\n"
    "            with self._cache_persist_lock:\n"
    "                with self._cache_lock:\n"
    "                    self._cache_generation += 1\n"
    "                    self._history_snapshot_revision += 1\n"
)
DESTROY_REPLACEMENT = (
    "    def destroy(self):\n"
    "        with self._history_context_lock:\n"
    "            with self._cache_persist_lock:\n"
    "                with self._cache_lock:\n"
    "                    self._cache_generation += 1\n"
    "                    self._resource_search_layered_shadow_sampled_generation = None\n"
    "                    self._resource_search_layered_shadow_last_report = None\n"
    "                    self._history_snapshot_revision += 1\n"
)
WORKER_ANCHOR = (
    "            self._resource_search_admissions += 1\n\n"
    "        def worker():\n"
    "            try:\n"
)
WORKER_REPLACEMENT = (
    "            self._resource_search_admissions += 1\n\n"
    "        def worker():\n"
    "            shadow_payload = None\n"
    "            try:\n"
)
ORDER_ANCHOR = (
    "                candidates = self._resource_fair_candidate_order(\n"
    "                    candidates,\n"
    "                    item,\n"
    "                    modes=sorted(modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99)),\n"
    "                )\n"
)
ORDER_REPLACEMENT = (
    "                shadow_rows = (\n"
    "                    candidates if self._resource_candidate_shadow_enabled else None\n"
    "                )\n"
    "                shadow_modes = tuple(sorted(\n"
    "                    modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99),\n"
    "                ))\n"
    "                candidates = self._resource_fair_candidate_order(\n"
    "                    candidates, item, modes=shadow_modes,\n"
    "                )\n"
)
PAYLOAD_ANCHOR = (
    "                if committed:\n"
    "                    final_group_count = self._validated_resource_group_count(playable)\n"
    "                    if final_group_count > first_refreshed_groups:\n"
    "                        self._schedule_active_detail_refresh(item)\n"
    "            except Exception:\n"
)
PAYLOAD_REPLACEMENT = (
    "                if committed:\n"
    "                    final_group_count = self._validated_resource_group_count(playable)\n"
    "                    if final_group_count > first_refreshed_groups:\n"
    "                        self._schedule_active_detail_refresh(item)\n"
    "                    if shadow_rows is not None:\n"
    "                        shadow_payload = (\n"
    "                            candidates,\n"
    "                            shadow_rows,\n"
    "                            shadow_modes,\n"
    "                        )\n"
    "            except Exception:\n"
)
CALL_ANCHOR = (
    "                    self._resource_search_admissions = max(0, self._resource_search_admissions - 1)\n\n"
    "        try:\n"
    "            self._resource_search_executor.submit(worker)\n"
)
CALL_REPLACEMENT = (
    "                    self._resource_search_admissions = max(0, self._resource_search_admissions - 1)\n"
    "                if shadow_payload is not None:\n"
    "                    legacy_rows, shadow_rows, shadow_modes = shadow_payload\n"
    "                    run_background_resource_candidate_shadow(\n"
    "                        self, legacy_rows, shadow_rows, item=item,\n"
    "                        cache_key=cache_key, generation=generation, modes=shadow_modes,\n"
    "                    )\n\n"
    "        try:\n"
    "            self._resource_search_executor.submit(worker)\n"
)
LAYERED_ANCHOR = (
    "        if bound and all(str(row.get(\"vod_id\") or row.get(\"id\") or \"\") != bound for row in rows):\n"
    "            rows.append({\"vod_id\": bound, \"vod_name\": title, \"_resource_mode\": \"vod\"})\n"
    "        ordered = self._resource_fair_candidate_order(\n"
)
LAYERED_REPLACEMENT = (
    "        if bound and all(str(row.get(\"vod_id\") or row.get(\"id\") or \"\") != bound for row in rows):\n"
    "            rows.append({\"vod_id\": bound, \"vod_name\": title, \"_resource_mode\": \"vod\"})\n"
    "        if self._resource_search_layered_shadow_enabled:\n"
    "            try:\n"
    "                recent_resource_id = \"\"\n"
    "                recent_route = item.get(\"last_play_route\") if isinstance(item.get(\"last_play_route\"), dict) else {}\n"
    "                if recent_route:\n"
    "                    recent_backend = str(recent_route.get(\"backend\") or \"\")\n"
    "                    if not recent_backend or recent_backend == self._resource_capability_identity():\n"
    "                        recent_resource_id = str(recent_route.get(\"resourceId\") or \"\").strip()\n"
    "                run_resource_search_layered_shadow(\n"
    "                    self, rows,\n"
    "                    cache_key=self._resource_search_cache_key(item, \"layered-shadow\"),\n"
    "                    cached_rows=cached_rows if supplement_modes else (),\n"
    "                    recent_resource_id=recent_resource_id,\n"
    "                    binding_resource_id=bound,\n"
    "                    available_modes=tuple(sorted(\n"
    "                        modes, key=lambda value: self.RESOURCE_MODE_PRIORITY.get(value, 99),\n"
    "                    )),\n"
    "                )\n"
    "            except Exception:\n"
    "                pass\n"
    "        ordered = self._resource_fair_candidate_order(\n"
)
INSERTIONS = (
    ("state", STATE_ANCHOR, STATE_REPLACEMENT),
    ("reset", RESET_ANCHOR, RESET_REPLACEMENT),
    ("destroy", DESTROY_ANCHOR, DESTROY_REPLACEMENT),
    ("worker", WORKER_ANCHOR, WORKER_REPLACEMENT),
    ("order", ORDER_ANCHOR, ORDER_REPLACEMENT),
    ("payload", PAYLOAD_ANCHOR, PAYLOAD_REPLACEMENT),
    ("call", CALL_ANCHOR, CALL_REPLACEMENT),
    ("layered", LAYERED_ANCHOR, LAYERED_REPLACEMENT),
)


def _replace_once(text, anchor, replacement, label):
    count = text.count(anchor)
    if count != 1:
        raise RuntimeOverlayError(
            "runtime overlay anchor %s must occur once, found %d" % (label, count)
        )
    return text.replace(anchor, replacement, 1)


def apply_runtime_overlay(source):
    try:
        text = bytes(source).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeOverlayError("runtime overlay input is not valid UTF-8") from exc
    input_bytes = text.encode("utf-8")
    for label, anchor, replacement in INSERTIONS:
        text = _replace_once(text, anchor, replacement, label)
    try:
        tree = ast.parse(text, filename="build/v80-dev/runtime-shadow-overlay.py")
        compile(tree, "build/v80-dev/runtime-shadow-overlay.py", "exec")
    except SyntaxError as exc:
        raise RuntimeOverlayError("runtime overlay output is invalid: %s" % exc) from exc

    spiders = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Spider"
    ]
    if len(spiders) != 1:
        raise RuntimeOverlayError("runtime overlay requires exactly one Spider class")
    candidate_calls = [
        node for node in ast.walk(spiders[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_background_resource_candidate_shadow"
    ]
    if len(candidate_calls) != 1:
        raise RuntimeOverlayError("runtime overlay must add exactly one shadow call")
    layered_calls = [
        node for node in ast.walk(spiders[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_resource_search_layered_shadow"
    ]
    if len(layered_calls) != 1:
        raise RuntimeOverlayError("runtime overlay must add exactly one layered shadow call")

    data = text.encode("utf-8")
    return {
        "bytes": data,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "input_size": len(input_bytes),
        "input_sha256": hashlib.sha256(input_bytes).hexdigest().upper(),
        "insertions": tuple(label for label, _anchor, _replacement in INSERTIONS),
    }
