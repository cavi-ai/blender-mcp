"""Traverse curves bound through active actions, NLA slots and drivers."""


def bound_curves(owner):
    animation=getattr(owner,'animation_data',None)
    if animation is None:return
    yield from animation.drivers
    bindings=[(animation.action,animation.action_slot)]
    pending=[strip for track in animation.nla_tracks for strip in track.strips]
    while pending:
        strip=pending.pop()
        pending.extend(getattr(strip,'strips',()))
        if strip.action is not None:bindings.append((strip.action,strip.action_slot))
    for action,slot in bindings:
        if action is None:continue
        yield from getattr(action,'fcurves',())
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip,'channelbags',()):
                    if slot is None or bag.slot_handle==slot.handle:yield from bag.fcurves


def require_static(matches,subject,*,root=None):
    """Check bound curves and external driver aliases across native ID owners."""
    import bpy

    mapping=bpy.data.user_map()
    owners=set(mapping)
    if root is not None:owners.add(root)
    for users in mapping.values():owners.update(users)
    owners.update(tree for owner in tuple(owners) if (tree:=getattr(owner,'node_tree',None)) is not None)
    for owner in owners:
        if any(matches(owner,curve.data_path) for curve in bound_curves(owner)):
            raise ValueError(subject+' is animated or driven; edit its animation before changing static data')
        animation=getattr(owner,'animation_data',None)
        for curve in animation.drivers if animation else ():
            for variable in curve.driver.variables:
                if any(matches(t.id,t.data_path) for t in variable.targets):
                    raise ValueError('A driver references '+subject+'; detach that reference before editing')
