"""Apply the same explicit root overrides to raw Restore controls."""


def root_properties(contract, entry):
    properties = {name.casefold(): (name, value) for name, value in contract['Properties'].items()}
    properties.update({name.casefold(): (name, value) for name, value in contract.get('EntryProperties', {}).get(entry, {}).items()})
    return dict(properties.values())
