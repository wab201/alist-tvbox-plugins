def _decision(admit, reason):
    return {"admit": admit, "reason": reason}


def decide_resource_output_admission(
    *,
    enabled: bool,
    development_build_verified: bool,
    candidate_shadow_verified: bool,
    layered_shadow_verified: bool,
    atvp_compatibility_verified: bool,
    dual_runtime_verified: bool,
    fongmi_category_verified: bool,
    public_v70_locked: bool,
    public_output_untouched: bool,
) -> dict:
    """Admit a future output switch only when every frozen proof is explicit."""
    if enabled is not True:
        return _decision(False, "disabled")

    requirements = (
        (development_build_verified, "development_build_unverified"),
        (candidate_shadow_verified, "candidate_shadow_unverified"),
        (layered_shadow_verified, "layered_shadow_unverified"),
        (atvp_compatibility_verified, "atvp_compatibility_unverified"),
        (dual_runtime_verified, "dual_runtime_unverified"),
        (fongmi_category_verified, "fongmi_category_unverified"),
        (public_v70_locked, "public_v70_unlocked"),
        (public_output_untouched, "public_output_touched"),
    )
    for verified, reason in requirements:
        if verified is not True:
            return _decision(False, reason)
    return _decision(True, "admitted")
