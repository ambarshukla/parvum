"""The tenant mapping is demo configuration — these tests pin its invariants."""

import pytest

from parvum_export.tenants import TENANT_CLIENTS, client_tenants, schema_for
from parvum_reference.ownership import OWNERSHIP


def test_every_client_family_is_advised_by_exactly_one_firm():
    """A new family in the universe must be assigned a firm before it can be
    served — this is the test that forces that conversation."""
    universe = {client.client_id for client in OWNERSHIP.clients}
    assert set(client_tenants().keys()) == universe


def test_schema_names_match_the_java_side_convention():
    assert schema_for("aldergate") == "tenant_aldergate"
    assert [schema_for(tenant) for tenant in TENANT_CLIENTS] == [
        "tenant_aldergate",
        "tenant_stonefield",
    ]


@pytest.mark.parametrize("hostile", ['bad"id', "Tenant", "", "1abc", "a-b", "a;drop"])
def test_tenant_ids_that_could_escape_an_identifier_are_rejected(hostile):
    with pytest.raises(ValueError):
        schema_for(hostile)
