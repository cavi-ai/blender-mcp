"""Shared material-slot capture, assignment and rollback."""


def capture(values):
    return ({value.data:list(value.data.materials) for value in values},
            {value:[(s.link,s.material) for s in value.material_slots] for value in values})


def bind(values, material, slot, modes):
    for value in values:
        if not value.material_slots:
            value.data.materials.append(None if modes[value]=='OBJECT' else material)
        value.material_slots[slot].link=modes[value]
        value.material_slots[slot].material=material


def restore(snapshot):
    data_slots,object_slots=snapshot
    for data,previous in data_slots.items():
        if not previous and data.materials:
            data.materials.clear()
        else:
            while len(data.materials)>len(previous):
                data.materials.pop(index=len(data.materials)-1)
        for index,old in enumerate(previous):
            if data.materials[index]!=old:
                data.materials[index]=old
    for value,previous in object_slots.items():
        for index,(link,old) in enumerate(previous):
            slot=value.material_slots[index]
            if slot.link!=link:
                slot.link=link
            if slot.material!=old:
                slot.material=old
