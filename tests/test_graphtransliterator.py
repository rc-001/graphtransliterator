#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `graphtransliterator` package."""

import pytest
import yaml
from graphtransliterator import GraphTransliterator
from graphtransliterator import process, validate
from graphtransliterator.types import (
    DirectedGraph, OnMatchRule, TransliteratorOutput, TransliterationRule,
    Whitespace
)
from graphtransliterator.exceptions import (
    NoMatchingTransliterationRule, UnrecognizableInputToken
)
yaml_for_test = r"""
tokens:
  a: [token, class1]
  b: [token, class2]
  u: [token]
  ' ': [wb]
rules:
  a: A
  b: B
  <wb> u: \N{DEVANAGARI LETTER U}
onmatch_rules:
  -
    <class1> + <class2>: ","
  -
    <class1> + <token>: \N{DEVANAGARI SIGN VIRAMA}
whitespace:
  default: ' '
  token_class: 'wb'
  consolidate: true
"""


def test_GraphTransliterator_from_YAML():
    """Test YAML loading of GraphTransliterator."""
    good_yaml = """
      tokens:
        a: [class1]
        ' ': [wb]
      rules:
        a: A
      whitespace:
        default: ' '
        consolidate: true
        token_class: wb
    """
    assert GraphTransliterator.from_yaml(good_yaml)
    bad_yaml = """
      tokens:
        a: class1
        ' ': wb
      rules:
        a: A
      whitespace:
        default: ' '
        consolidate: true
        token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)

    bad_yaml = """
          rules:
            a: A
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)
    bad_yaml = """
          tokens:
            a: [class1]
            ' ': [wb]
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)
    bad_yaml = """
          tokens:
            a: [class1]
            ' ': [wb]
          rules:
            a: A
    """
    bad_yaml = """
          tokens:
            a: [class1]
            ' ': [wb]
          rules:
            b: A
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)

    bad_yaml = """
          tokens:
            a: [class1]
            ' ': [wb]
          rules:
            (b) a: A
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)

    bad_yaml = """
          tokens:
            a: [class1]
            ' ': [wb]
          rules:
            a (b): A
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)

    bad_yaml = """
          tokens:
            a: [class1]
            ' ': [wb]
          rules:
            a <class_nonexisting>: A
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)

    # test for bad tokens
    bad_yaml = """
          tokens: '7'
          rules:
            a <class_nonexisting>: A
          whitespace:
            default: ' '
            consolidate: true
            token_class: wb
    """
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(bad_yaml)


def test_graphtransliterator_process():
    """Test graphtransliterator proccessing of rules."""

    data = yaml.safe_load(yaml_for_test)

    assert process._process_rules({'a': 'A'})[0]['tokens'] == ['a']
    assert process._process_rules({'a': 'A'})[0]['production'] == 'A'
    assert process._process_onmatch_rules(
        data['onmatch_rules'])[0]['prev_classes'][0] == 'class1'
    assert process._process_onmatch_rules(
        data['onmatch_rules'])[0]['next_classes'][0] == 'class2'


def test_graphtransliterator_types():
    """Test internal types."""
    tr = TransliterationRule(
        production='A',
        prev_classes=None,
        prev_tokens=None,
        tokens=['a'],
        next_tokens=None,
        next_classes=None,
        cost=1
    )
    assert tr.cost == 1
    assert TransliteratorOutput([tr], 'A').output == 'A'
    assert OnMatchRule(prev_classes=['class1'],
                       next_classes=['class2'],
                       production=',')
    assert Whitespace(default=' ',
                      token_class='wb',
                      consolidate=False)

    graph = DirectedGraph()

    assert len(graph.node) == 0
    assert len(graph.edge) == 0

    graph.add_node({"type": "test1"})
    graph.add_node({"type": "test2"})
    assert graph.node[0]['type'] == 'test1'
    assert graph.node[1]['type'] == 'test2'

    graph.add_edge(0, 1, {"type": "edge_test1"})
    assert graph.edge[0][1]['type'] == 'edge_test1'
    assert type(graph.to_dict()) == dict

    with pytest.raises(ValueError):
        graph.add_edge(0, 7, {})

    with pytest.raises(ValueError):
        graph.add_edge(7, 0, {})

    with pytest.raises(ValueError):
        graph.add_edge(0, 1, 'not a dict')


def test_graphtransliterator_validate_settings():
    """Test graph transliterator validation of settings."""
    settings = yaml.safe_load(yaml_for_test)
    # check for bad tokens
    settings['tokens'] = 'bad token'
    with pytest.raises(ValueError):
        validate.validate_settings(settings['tokens'],
                                   settings['rules'],
                                   settings['onmatch_rules'],
                                   settings['whitespace'],
                                   {})


def test_GraphTransliterator_transliterate(tmpdir):
    """Test GraphTransliterator transliterate."""
    YAML = r"""
    tokens:
        a: [class_a]
        b: [class_b]
        c: [class_c]
        " ": [wb]
        Aa: [contrained_rule]
    rules:
        a: A
        b: B
        <class_c> a: A(AFTER_CLASS_C)
        (<class_c> b) a: A(AFTER_B_AND_CLASS_C)
        (<class_c> b b) a: A(AFTER_BB_AND_CLASS_C)
        a <class_c>: A(BEFORE_CLASS_C)
        a (c <class_b>): A(BEFORE_C_AND_CLASS_B)
        c: C
        c c: C*2
        a (b b): A(BEFORE_B_B)
        (b b) a: A(AFTER_B_B)
        <wb> Aa: A(ONLY_A_CONSTRAINED_RULE)
    onmatch_rules:
        -
            <class_a> <class_b> + <class_a> <class_b>: "!"
        -
            <class_a> + <class_b>: ","
    whitespace:
        default: ' '
        consolidate: True
        token_class: wb
    """
    gt = GraphTransliterator.from_yaml(YAML)
    # rules with single token
    assert gt.transliterate('a') == 'A'
    # rules with multiple tokens
    assert gt.transliterate('aa') == 'AA'
    # rules with multiple tokens (for rule_key)
    assert gt.transliterate('cc') == 'C*2'
    # # rules with multiple tokens overlapping end of tokens
    # assert gt.transliterate('c') == 'C'

    # rules with prev class
    assert gt.transliterate('ca') == 'CA(AFTER_CLASS_C)'
    # rules with prev class and prev token
    assert gt.transliterate('cba') == 'CBA(AFTER_B_AND_CLASS_C)'
    # rules with prev class and prev tokens
    assert gt.transliterate('cbba') == 'CBBA(AFTER_BB_AND_CLASS_C)'
    # rules with next class
    assert gt.transliterate('ac') == 'A(BEFORE_CLASS_C)C'
    # rules with next class and next tokens
    assert gt.transliterate('acb') == 'A(BEFORE_C_AND_CLASS_B)CB'
    # rules with onmatch rule of length 1
    assert gt.transliterate('ab') == 'A,B'
    # rules that only have constraints on first element
    assert gt.transliterate('Aa') == 'A(ONLY_A_CONSTRAINED_RULE)'
    # test whitespace consolidation
    assert gt.transliterate(" a") == "A"
    # test whitespace consolidation following
    assert gt.transliterate("a ") == "A"

    # rules with longer onmatch rules
    assert gt.transliterate('abab') == 'A,B!A,B'
    # test last_matched_tokens
    assert gt.last_matched_tokens == [['a'], ['b'], ['a'], ['b']]

    # test last_matched_rules
    assert len(gt.last_matched_rules) == 4

    # test serialization
    assert gt.serialize()['_graph']['edge']


def test_match_all():
    """Test GraphTransliterator transliterate."""
    YAML = r"""
    tokens:
        a: [class_a]
        " ": [wb]
    rules:
        a: A
        a a: A*2
    whitespace:
        default: ' '
        consolidate: True
        token_class: wb
    """
    gt = GraphTransliterator.from_yaml(YAML)
    assert gt.rules[0].cost < gt.rules[1].cost

    tokens = gt.tokenize('aa')
    assert gt.match_at(1, tokens, match_all=False) == 0
    assert gt.match_at(1, tokens, match_all=True) == [0, 1]


def test_GraphTransliterator(tmpdir):
    """Test GraphTransliterator."""
    yaml_str = r"""
    tokens:
      a: [token, class1]
      b: [token, class2]
      u: [token]
      ' ': [wb]
    rules:
      a: A
      b: B
      <wb> u: \N{DEVANAGARI LETTER U}
    onmatch_rules:
      -
        <class1> + <class2>: ","
      -
        <class1> + <token>: \N{DEVANAGARI SIGN VIRAMA}
    whitespace:
      default: ' '
      token_class: 'wb'
      consolidate: true
    """

    input_dict = yaml.safe_load(yaml_str)
    assert 'a' in GraphTransliterator.from_dict(input_dict).tokens.keys()
    gt = GraphTransliterator.from_dict(input_dict)
    assert gt.onmatch_rules[0].production == ','
    assert gt.tokens
    assert gt.rules
    assert gt.whitespace
    assert gt.whitespace.default
    assert gt.whitespace.token_class
    assert gt.whitespace.consolidate

    yaml_file = tmpdir.join("yaml_test.yaml")
    yaml_filename = str(yaml_file)
    yaml_file.write(yaml_str)

    assert yaml_file.read() == yaml_str

    assert GraphTransliterator.from_yaml_file(yaml_filename)

    assert len(set(GraphTransliterator.from_dict(input_dict).tokens)) == 4

    assert GraphTransliterator.from_yaml(yaml_str).transliterate("ab") == 'A,B'
    assert GraphTransliterator.from_yaml_file(
                                                 yaml_filename
                                             ).transliterate('ab') == 'A,B'
    assert GraphTransliterator.from_dict(
        {'tokens': {'a': ['class_a'], 'b': ['class_b'], ' ': ['wb']},
         'onmatch_rules': [{'<class_a> + <class_b>': ','}],
         'whitespace': {'default': ' ',
                        'token_class': 'wb',
                        'consolidate': True},
         'rules': {'a': 'A', 'b': 'B'}},
        raw=True
    ).transliterate("ab") == 'A,B'


def test_GraphTransliterator_ignore_exceptions():
    # if ignore_exceptions is not set and no matching transliteration rule
    # raise NoMatchingTransliterationRule exception
    yaml_str = """
        tokens:
           a: [class1]
           b: [class1]
           ' ': [wb]
        rules:
           a a: B2
           b: b
        whitespace:
           default: ' '
           consolidate: true
           token_class: wb
        """
    # check that ignore_exceptions works
    assert GraphTransliterator.from_yaml(yaml_str).transliterate('a') == ''
    with pytest.raises(NoMatchingTransliterationRule):
        gt = GraphTransliterator.from_yaml(yaml_str, ignore_exceptions=False)
        assert gt.ignore_exceptions is False
        gt.transliterate('a')
    with pytest.raises(UnrecognizableInputToken):
        gt = GraphTransliterator.from_yaml(yaml_str, ignore_exceptions=False)
        assert gt.ignore_exceptions is False
        gt.transliterate('!')
    with pytest.raises(UnrecognizableInputToken):
        gt = GraphTransliterator.from_yaml(yaml_str, ignore_exceptions=False)
        assert gt.ignore_exceptions is False
        gt.transliterate('b!')
    # test ignore_exceptions keyword value checking on init
    with pytest.raises(ValueError):
        GraphTransliterator.from_yaml(yaml_str, ignore_exceptions="maybe")
    # test ignore_exceptions keyword property
    gt = GraphTransliterator.from_yaml(yaml_str)
    # test ignore_exceptions setter and property
    gt.ignore_exceptions = True
    assert gt.ignore_exceptions is True
    gt.ignore_exceptions = False
    assert gt.ignore_exceptions is False
    # test ignore_exceptions setter exception handling
    with pytest.raises(ValueError):
        gt.ignore_exceptions = "Maybe"



def test_GraphTransliterator_types():
    """Test internal types."""
    pr = TransliterationRule(production='A',
                             prev_classes=None,
                             prev_tokens=None,
                             tokens=['a'],
                             next_tokens=None,
                             next_classes=None,
                             cost=1)
    assert pr.cost == 1
    assert TransliteratorOutput([pr], 'A').output == 'A'
    assert OnMatchRule(prev_classes=['class1'],
                       next_classes=['class2'],
                       production=',')
    assert Whitespace(default=' ',
                      token_class='wb',
                      consolidate=False)

    graph = DirectedGraph()

    assert len(graph.node) == 0
    assert len(graph.edge) == 0

    graph.add_node({"type": "test1"})
    graph.add_node({"type": "test2"})
    assert graph.node[0]['type'] == 'test1'
    assert graph.node[1]['type'] == 'test2'

    graph.add_edge(0, 1, {"type": "edge_test1"})
    assert graph.edge[0][1]['type'] == 'edge_test1'


def test_GraphTransliterator_productions():
    """Test productions."""
    tokens = {'ab': ['class_ab'], ' ': ['wb']}
    whitespace = {'default': ' ', 'token_class': 'wb', 'consolidate': True}
    rules = {'ab': 'AB', ' ': '_'}
    settings = {'tokens': tokens, 'rules': rules, 'whitespace': whitespace}
    assert set(GraphTransliterator.from_dict(settings).productions) == \
        set(['AB', '_'])


def test_GraphTransliterator_pruned_of():
    gt = GraphTransliterator.from_yaml("""
            tokens:
               a: [class1]
               b: [class2]
               ' ': [wb]
            rules:
               a: A
               b: B
            whitespace:
               default: ' '
               consolidate: true
               token_class: wb
        """)
    assert len(gt.rules) == 2
    assert len(gt.pruned_of('B').rules) == 1
    assert gt.pruned_of('B').rules[0].production == 'A'


def test_GraphTransliterator_graph():
    """Test graph."""
    tokens = {'ab': ['class_ab'], ' ': ['wb']}
    whitespace = {'default': ' ', 'token_class': 'wb', 'consolidate': True}
    rules = {'ab': 'AB', ' ': '_'}
    settings = {'tokens': tokens, 'rules': rules, 'whitespace': whitespace}
    gt = GraphTransliterator.from_dict(settings)
    assert gt._graph
    assert gt._graph.node[0]['type'] == 'Start'  # test for Start
    assert gt
