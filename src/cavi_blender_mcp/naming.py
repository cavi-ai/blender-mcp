"""Game-engine object naming rules; no application dependency."""

import re

LOD = re.compile(r"_LOD(\d+)$")
COLLISION_PREFIXES = ("UCX_", "UBX_", "USP_")
PAIR = re.compile(r"_(low|high)$", re.IGNORECASE)
DEFAULT_RULES = {"mesh_prefix": None, "lod_suffix": "_LOD{n}",
                 "collision_prefixes": list(COLLISION_PREFIXES)}


def base_name(name):
    return LOD.sub("", name)


def pair_base(name):
    return LOD.sub("", PAIR.sub("", name))


def rules(naming):
    merged = {**DEFAULT_RULES, **(naming or {})}
    if set(merged) != set(DEFAULT_RULES):
        raise ValueError("naming accepts mesh_prefix, lod_suffix and collision_prefixes")
    suffix, prefixes = merged["lod_suffix"], merged["collision_prefixes"]
    if not isinstance(suffix, str) or suffix.count("{n}") != 1 or len(suffix) > 32:
        raise ValueError("lod_suffix must contain {n} once")
    if not isinstance(prefixes, list) or len(prefixes) > 8 or not all(
        isinstance(p, str) and 0 < len(p) <= 16 for p in prefixes
    ):
        raise ValueError("collision_prefixes must be up to 8 short strings")
    prefix = merged["mesh_prefix"]
    if prefix is not None and (not isinstance(prefix, str) or len(prefix) > 16):
        raise ValueError("mesh_prefix must be a short string")
    return merged


def lint(name, naming=None):
    merged = rules(naming)
    issues = []
    if re.search(r"\.\d{3}$", name):
        issues.append("blender_duplicate_suffix")
    if re.search(r"\s", name):
        issues.append("whitespace")
    if not name.isascii():
        issues.append("non_ascii")
    prefix = next((p for p in merged["collision_prefixes"] if name.startswith(p)), None)
    if prefix:
        match = re.fullmatch(re.escape(prefix) + r"(.+)_(\d+)", name)
        if not match:
            issues.append("collision_missing_index")
        return {"role": "collision", "base": match.group(1) if match else None,
                "issues": issues}
    head, tail = merged["lod_suffix"].split("{n}")
    lod = re.search(re.escape(head) + r"(\d+)" + re.escape(tail) + "$", name)
    if not lod and re.search(r"lod_?\d+$", name, re.IGNORECASE):
        issues.append("lod_suffix_format")
    if merged["mesh_prefix"] and not name.startswith(merged["mesh_prefix"]):
        issues.append("missing_mesh_prefix")
    return {"role": "lod" if lod else "mesh", "lod": int(lod.group(1)) if lod else None,
            "issues": issues}
