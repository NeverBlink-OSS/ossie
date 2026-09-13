# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Tests for the Ossie <-> LinkML converters.

The translation itself lives in `linkml_scala` (the `neverblink-linkml`
package), which has its own test suite: 400+ tests, including unit tests,
integration with Ossie JSON Schema and validator, round-trip tests, and
expression parser fuzzing.

The tests here cover the integration: that the wiring works correctly and
that a round-trip through LinkML keeps the ontology intact."""

from __future__ import annotations

import json

import linkml_scala
import pytest
import yaml

from ossie_ontology.converter.linkml_to_ossie.converter import LinkmlToOssieConverter
from ossie_ontology.converter.ossie_to_linkml.converter import OssieToLinkmlConverter
from ossie_ontology.model import OssieOntology
from ossie_ontology.spec import OssieSpec


@pytest.fixture
def flights_linkml(flights_model: OssieOntology) -> str:
    return OssieToLinkmlConverter.convert(flights_model)


# ----- Ossie -> LinkML ---------------------------------------------------

def test_schema_loads_without_errors(flights_linkml: str):
    with linkml_scala.load_string(flights_linkml) as schema:
        # A schema can load and still have errors against it, so check the
        # report rather than just that the load returned.
        assert schema.issues(linkml_scala.ERROR) == []
        assert schema.issues(linkml_scala.FATAL) == []


def test_schema_carries_concepts(flights_linkml: str):
    schema = yaml.safe_load(flights_linkml)
    assert schema["name"] == "Flights"
    assert schema["description"] == "Ontology of flights into and out of airports."
    # Entity types become classes, value types become types.
    assert {"Airport", "Flight", "Carrier"} <= set(schema["classes"])
    assert {"CancelationCode", "DegreesLatitude"} <= set(schema["types"])
    # Relationships under a concept become that class's attributes.
    assert "code" in schema["classes"]["Airport"]["attributes"]


def test_schema_id_defaults_and_can_be_overridden(flights_model: OssieOntology):
    # An Ossie ontology has no id of its own, so one is made up from its name.
    assert yaml.safe_load(OssieToLinkmlConverter.convert(flights_model))["id"] == "https://example.org/flights"

    given = "https://ossie.apache.org/flights"
    assert yaml.safe_load(OssieToLinkmlConverter.convert(flights_model, schema_id=given))["id"] == given


def test_json_output_format(flights_model: OssieOntology):
    schema = json.loads(OssieToLinkmlConverter.convert(flights_model, output_format="json"))
    assert schema["name"] == "Flights"


def test_convert_spec_matches_convert(flights_model: OssieOntology, flights_path):
    """Going straight from the spec DTO describes the same schema as going via
    the runtime model.

    Compared as parsed YAML, not as text: building the runtime model sorts
    concepts topologically, so the two agree on content but not on the order
    classes and types are emitted in.
    """
    spec = OssieSpec.load_yaml(flights_path.read_text(encoding="utf-8"))
    assert yaml.safe_load(OssieToLinkmlConverter.convert_spec(spec)) == yaml.safe_load(
        OssieToLinkmlConverter.convert(flights_model)
    )


# ----- LinkML -> Ossie ---------------------------------------------------

def test_convert_text_returns_model(flights_linkml: str):
    model = LinkmlToOssieConverter().convert_text(flights_linkml)
    assert model.name == "Flights"
    assert model.version == "0.2.0.dev0"
    assert model.description == "Ontology of flights into and out of airports."


def test_convert_file_reads_from_disk(flights_linkml: str, tmp_path):
    path = tmp_path / "flights.linkml.yaml"
    path.write_text(flights_linkml, encoding="utf-8")
    assert LinkmlToOssieConverter().convert_file(path).name == "Flights"


def test_convert_to_spec_stops_at_the_dto(flights_linkml: str):
    with linkml_scala.load_string(flights_linkml) as schema:
        spec = LinkmlToOssieConverter().convert_to_spec(schema)
    assert isinstance(spec, OssieSpec)
    assert spec.name == "Flights"


def test_converters_do_not_share_formula_factories():
    a, b = LinkmlToOssieConverter(), LinkmlToOssieConverter()
    assert a._formula_factory is not b._formula_factory
    assert a._mapping_formula_factory is not b._mapping_formula_factory


# ----- Round-trip --------------------------------------------------------

def test_roundtrip_preserves_concepts_and_relationships(flights_model: OssieOntology, flights_linkml: str):
    back = LinkmlToOssieConverter().convert_text(flights_linkml)

    def names(model: OssieOntology) -> tuple[set[str], set[str]]:
        ontology = model.ontology
        return (
            {c.name for c in ontology.concepts(exclude_builtin=True)},
            {r.full_name for r in ontology.relationships},
        )

    assert names(back) == names(flights_model)


def test_roundtrip_preserves_concept_types_and_identifiers(flights_model: OssieOntology, flights_linkml: str):
    back = LinkmlToOssieConverter().convert_text(flights_linkml)
    for concept in flights_model.ontology.concepts(exclude_builtin=True):
        returned = back.ontology.lookup_concept(concept.name)
        assert returned is not None, concept.name
        assert returned.type == concept.type, concept.name
        assert set(returned.identify_by) == set(concept.identify_by), concept.name


def test_roundtrip_drops_ontology_mappings(flights_model: OssieOntology, flights_linkml: str):
    # Documents a known loss: LinkML describes types and their slots, so there
    # is nowhere to put datasets, join paths or metrics.
    assert flights_model.ontology_mappings != []
    assert LinkmlToOssieConverter().convert_text(flights_linkml).ontology_mappings == []
