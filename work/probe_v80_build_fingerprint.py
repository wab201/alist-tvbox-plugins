import argparse
import hashlib
import importlib.util
import re
from pathlib import Path


def load_module(path):
    spec = importlib.util.spec_from_file_location("v80_build_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_fingerprint_chain(source, digest, previous_stage, final_stage):
    if (
            previous_stage["size"] != final_stage["input_size"]
            or previous_stage["sha256"] != final_stage["input_sha256"]):
        raise RuntimeError("previous stage and final module fingerprints are disconnected")
    if final_stage["size"] != len(source) or final_stage["sha256"] != digest:
        raise RuntimeError("final module and assembled source fingerprints are disconnected")


def main():
    parser = argparse.ArgumentParser(
        description="Probe V80 assembled fingerprint without writing an output."
    )
    parser.add_argument("--expected-size", type=int)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    build = load_module(root / "tools" / "build_follow_plugin.py")
    manifest = build.load_manifest(
        root / "src" / "douban_tmdb_follow_single" / "release.json"
    )
    manifest["expected_size"] = args.expected_size or manifest["expected_size"]
    manifest["expected_sha256"] = "0" * 64
    digest = None
    for _attempt in range(2):
        try:
            build._assemble(manifest, root)
        except build.BuildError as exc:
            message = str(exc)
            size_match = re.fullmatch(
                r"assembled size mismatch: expected \d+, got (\d+)", message,
                flags=re.IGNORECASE,
            )
            if size_match:
                manifest["expected_size"] = int(size_match.group(1))
                continue
            digest_match = re.fullmatch(
                r"assembled sha256 mismatch: expected [0-9a-f]{64}, got ([0-9a-f]{64})",
                message,
                flags=re.IGNORECASE,
            )
            if digest_match:
                digest = digest_match.group(1).upper()
                break
            raise
    if digest is None:
        raise RuntimeError("probe unexpectedly matched the zero digest")

    manifest["expected_sha256"] = digest
    assembled = build._assemble(manifest, root)
    source = assembled[0]
    previous_stage = assembled[-2]
    final_module = assembled[-1]
    validate_fingerprint_chain(source, digest, previous_stage, final_module)
    print("size=%d" % len(source))
    print("sha256=%s" % digest)
    print("previous_stage_size=%d" % previous_stage["size"])
    print("previous_stage_sha256=%s" % previous_stage["sha256"])
    print("final_module_input_size=%d" % final_module["input_size"])
    print("final_module_input_sha256=%s" % final_module["input_sha256"])
    print("final_module_size=%d" % final_module["size"])
    print("final_module_sha256=%s" % final_module["sha256"])
    print("final_module_output_size=%d" % final_module["size"])
    print("final_module_output_sha256=%s" % final_module["sha256"])
    if hashlib.sha256(source).hexdigest().upper() != digest:
        raise RuntimeError("assembled bytes changed during fingerprint probe")


if __name__ == "__main__":
    main()
