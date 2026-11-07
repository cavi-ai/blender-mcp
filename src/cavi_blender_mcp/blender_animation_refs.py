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
