# -*- coding: utf-8 -*-

"""
GraphTransliterator core classes.
"""

import itertools
import logging
import pkg_resources
import re
import unicodedata
import yaml

from collections import deque
from .exceptions import (
    AmbiguousTransliterationRulesException,
    NoMatchingTransliterationRuleException,
    UnrecognizableInputTokenException,
)
from .process import _process_easyreading_settings
from .schemas import EasyReadingSettingsSchema, SettingsSchema
from .initialize import (
    _graph_from,
    _onmatch_rules_lookup,
    _tokenizer_pattern_from,
    _tokens_by_class_of,
)
from marshmallow import fields, post_load, Schema
from .schemas import (
    DirectedGraphSchema,
    TransliterationRuleSchema,
    WhitespaceSettingsSchema,
    OnMatchRuleSchema,
)

logger = logging.getLogger("graphtransliterator")


class GraphTransliteratorSchema(Schema):
    tokens = fields.Dict(
        keys=fields.Str(), values=fields.List(fields.Str()), required=True
    )
    rules = fields.Nested(TransliterationRuleSchema, many=True, required=True)
    whitespace = fields.Nested(WhitespaceSettingsSchema, many=False, required=True)
    onmatch_rules = fields.Nested(OnMatchRuleSchema, many=True, required=False)
    onmatch_rules_lookup = fields.Dict()
    metadata = fields.Dict(
        keys=fields.Str(), required=False  # no restriction on values
    )
    tokens_by_class = fields.Dict(keys=fields.Str(), values=fields.List(fields.Str))
    graph = fields.Nested(DirectedGraphSchema)
    tokenizer_pattern = fields.Str()
    graphtransliterator_version = fields.Str()

    class Meta:
        fields = (
            "tokens",
            "rules",
            "whitespace",
            "onmatch_rules",
            "metadata",
            # "check_ambiguity",
            "onmatch_rules_lookup",
            "tokens_by_class",
            "graph",
            "tokenizer_pattern",
            "graphtransliterator_version",
        )
        ordered = True

    @post_load
    def make_GraphTransliterator(self, data, **kwargs):
        # Convert lists to sets
        for key in ("tokens", "tokens_by_class"):
            data[key] = {k: set(v) for k, v in data[key].items()}
        # Do not check ambiguity if deserializing serialized GraphTransliterator
        data["check_ambiguity"] = False
        return GraphTransliterator(**data)


class GraphTransliterator:
    """
    A graph-based transliteration tool that lets you convert the symbols
    of one language or script to those of another using rules that you define.

    Transliteration of tokens of an input string to an output string is
    configured by: a set of input token types with classes, pattern-matching rules
    involving sequences of tokens as well as preceding or following tokens and
    token classes, insertion rules between matches, and optional consolidation
    of whitespace. Rules are ordered by specificity.

    Note
    ----
    This constructor does not validate settings and should typically not be called
    directly unless constructing a GraphTransliterator programmatically. Use
    :meth:`from_dict`, :meth:`from_easyreading_dict`, :meth:`from_yaml`, or
    :meth:`from_yaml_file` instead for "easy reading" support.
    Keyword parameters used here (``check_ambiguity``, ``ignore_errors``) can be passed
    from those other constructors.

    Parameters
    ----------
    tokens : `dict` of {`str`: `set` of `str`}
        Mapping of input token types to token classes
    rules : `list` of `dict`
        `list` of dictionaries of transliteration rules with keys:

            ``"prev_classes"``
              Token classes to be matched before previous tokens and tokens
              (`list` of `str`, or `None`)

            ``"prev_tokens"``
                Specific tokens to be matched before tokens
                (`list` of `str`, or `None`)

            ``"tokens"``
                Tokens to be matched
                (`list` of `str`)

            ``"next_tokens"``
                Specific tokens to follow matched tokens
                (`list` of `str`, or `None`)

            ``"next_classes"``
                Token classes to follow tokens and next tokens
                (`list` of `str`, or `None`)

    onmatch_rules : `list` of `dict`, or `None`
        Rules for output to be inserted between tokens
        of certain classes when a transliteration rule has been matched
        but before its production string has been added to the output,
        consisting of a list of dictionaries with the keys:

            ``"prev_classes"``
                Tokens classes to be found right before start of
                match with transliteration rule
                (`list` of `str`, or `None`)

            ``"next_classes"``
                Token classes to be found from start of transliteration rule
                (`list` of `str`, or `None`)

            ``"production"``
                String to be added to output before transliteration rule
                production
                (`str`)

    whitespace: `dict`
        Whitespace settings as dictionary with the keys:

            ``"default"``
                Default whitespace token
                (`str`)

            ``"token_class"``
                Comon class of whitespace tokens
                (`str`)

            ``"consolidate"``
                If true (default), sequential whitespace characters will be
                consolidated and treated as one token, and any whitespace
                at the start or end of the input will be removed.
                (`bool`)

    metadata: `dict` or `None`
        Metadata settings

    check_settings: `bool`, optional
        If true (default), the input settings are validated.

    check_ambiguity: `bool`, optional
        If true (default), transliteration rules are checked for ambiguity.

    ignore_errors: `bool`, optional
        If true, transliteration errors are ignored and do not raise an
        exception. The default is false.

    Example
    -------
    >>> from graphtransliterator import GraphTransliterator
    >>> settings = {
    ...    'tokens': {'a': set(['class1']),
    ...               'b': set(['class2']),
    ...               ' ': set(['wb']},
    ...    'rules': [
    ...        {'production': 'A', 'tokens': ['a']},
    ...        {'production': 'B', 'tokens': ['b']},
    ...        {'production': ' ', 'tokens': [' ']},
    ...        {'production': 'A*',
    ...         'prev_classes': ['class2'],
    ...         'prev_tokens': ['a'],
    ...         'tokens': ['a'],
    ...         'next_tokens': ['a'],
    ...         'next_classes': ['class2'] }],
    ...    'onmatch_rules': [
    ...        {'prev_classes': ['class1'],
    ...         'next_classes': ['class1'],
    ...         'production': ','}],
    ...    'whitespace': {
    ...        'default': ' ',
    ...        'consolidate': False,
    ...        'token_class': 'wb'},
    ...    'metadata': {
    ...        'author': 'Author McAuthorson',
    ...        'version': '0.0.1'}
    ... }
    >>> gt = GraphTransliterator(
    ...         settings['tokens'], settings['rules'], settings['onmatch_rules'],
    ...         settings['whitespace'], settings['metadata']
    ...      )
    >>> gt.transliterate('baaab')
    'BA,A*,AB'
    >>>

    See Also
    --------
    from_easyreading_dict : constructor from  dictionary in "easy reading" format
    from_yaml : constructor from YAML string in "easy reading" format
    from_yaml_file : constructor from YAML in "easy reading" format
"""  # noqa

    # def internal_settings_of(settings):
    #     metadata = settings.get("metadata")
    #     tokens = _tokens_of(settings["tokens"])
    #     tokens_by_class = _tokens_by_class_of(tokens)
    #     rules = sorted(
    #         [_transliteration_rule_of(rule) for rule in settings["rules"]],
    #         key=lambda transliteration_rule: transliteration_rule.cost,
    #     )
    #     onmatch_rules = [_onmatch_rule_of(_) for _ in settings.get("onmatch_rules")]
    #     onmatch_rules_lookup = _onmatch_rules_lookup(tokens, onmatch_rules)
    #     whitespace = _whitespace_rules_of(settings["whitespace"])
    #     ignore_errors = settings.get("ignore_errors", False)
    #
    #     return dict(
    #         metadata=metadata,
    #         tokens=tokens,
    #         tokens_by_class=tokens_by_class,
    #         rules=rules,
    #         onmatch_rules=onmatch_rules,
    #         onmatch_rules_lookup=onmatch_rules_lookup,
    #         whitespace=whitespace,
    #         ignore_errors=ignore_errors,
    #     )

    def __init__(
        self,
        tokens,
        rules,
        whitespace,
        onmatch_rules=None,
        metadata=None,
        ignore_errors=False,
        check_ambiguity=True,
        onmatch_rules_lookup=None,
        tokens_by_class=None,
        graph=None,
        tokenizer_pattern=None,
        graphtransliterator_version=None,
    ):
        self._tokens = tokens
        self._rules = rules
        self._tokens_by_class = tokens_by_class or _tokens_by_class_of(tokens)

        self._check_ambiguity = check_ambiguity  # used by pruned_of
        if check_ambiguity:
            self.check_for_ambiguity()

        self._whitespace = whitespace

        if onmatch_rules:
            self._onmatch_rules = onmatch_rules
            if onmatch_rules_lookup:
                self._onmatch_rules_lookup = onmatch_rules_lookup
            else:
                self._onmatch_rules_lookup = _onmatch_rules_lookup(
                    tokens, onmatch_rules
                )
        else:
            self._onmatch_rules = None
            self._onmatch_rules_lookup = None

        self._metadata = metadata
        self._ignore_errors = ignore_errors

        if not tokenizer_pattern:
            tokenizer_pattern = _tokenizer_pattern_from(list(tokens.keys()))
        self._tokenizer_pattern = tokenizer_pattern
        self._tokenizer = re.compile(tokenizer_pattern, re.S)

        if not graph:
            graph = _graph_from(rules)
        self._graph = graph

        self._rule_keys = []  # last matched rules

        # When or if necessary, add version checking here
        if not graphtransliterator_version:
            graphtransliterator_version = pkg_resources.require("graphtransliterator")[
                0
            ].version
        self._graphtransliterator_version = graphtransliterator_version

    def _match_constraints(self, source, target, token_i, tokens):
        """
        Match edge constraints.

        Called on edge before a rule. `token_i` is set to location right
        after tokens consumed.

        """
        target_edge = self._graph.edge[source][target]
        constraints = target_edge.get("constraints")
        if not constraints:
            return True
        for c_type, c_value in constraints.items():
            if c_type == "prev_tokens":
                num_tokens = len(self._graph.node[target]["rule"].tokens)
                # presume for rule (a) a, with input "aa"
                # ' ', a, a, ' '  start (token_i=3)
                #             ^
                #         ^       -1 subtract num_tokens
                #      ^          - len(c_value)
                start_at = token_i
                start_at -= num_tokens
                start_at -= len(c_value)

                if not self._match_tokens(
                    start_at,
                    c_value,
                    tokens,
                    check_prev=True,
                    check_next=False,
                    by_class=False,
                ):
                    return False
            elif c_type == "next_tokens":
                # presume for rule a (a), with input "aa"
                # ' ', a, a, ' '  start (token_i=2)
                #         ^
                start_at = token_i

                if not self._match_tokens(
                    start_at,
                    c_value,
                    tokens,
                    check_prev=False,
                    check_next=True,
                    by_class=False,
                ):
                    return False

            elif c_type == "prev_classes":
                num_tokens = len(self._graph.node[target]["rule"].tokens)
                # presume for rule (a <class_a>) a, with input "aaa"
                # ' ', a, a, a, ' '
                #                ^     start (token_i=4)
                #            ^         -num_tokens
                #         ^            -len(prev_tokens)
                #  ^                   -len(prev_classes)
                start_at = token_i
                start_at -= num_tokens
                prev_tokens = constraints.get("prev_tokens")
                if prev_tokens:
                    start_at -= len(prev_tokens)
                start_at -= len(c_value)
                if not self._match_tokens(
                    start_at,
                    c_value,
                    tokens,
                    check_prev=True,
                    check_next=False,
                    by_class=True,
                ):
                    return False

            elif c_type == "next_classes":
                # presume for rule a (a <class_a>), with input "aaa"
                # ' ', a, a, a, ' '
                #         ^          start (token_i=2)
                #            ^       + len of next_tokens (a)
                start_at = token_i
                next_tokens = constraints.get("next_tokens")
                if next_tokens:
                    start_at += len(next_tokens)
                if not self._match_tokens(
                    start_at,
                    c_value,
                    tokens,
                    check_prev=False,
                    check_next=True,
                    by_class=True,
                ):
                    return False

        return True

    def match_at(self, token_i, tokens, match_all=False):
        """
        Match best (least costly) transliteration rule at a given index in the
        input tokens and return the index to  that rule. Optionally, return all
        rules that match.

        Parameters
        ----------
        token_i : `int`
            Location in `tokens` at which to begin
        tokens : `list` of `str`
            List of tokens
        match_all : `bool`, optional
            If true, return the index of all rules matching at the given
            index. The default is false.

        Returns
        -------
        `int`, `None`, or `list` of `int`
            Index of matching transliteration rule in
            :attr:`GraphTransliterator.rules` or None. Returns a `list` of
            `int` or an empty `list` if ``match_all`` is true.

        Note
        ----
        Expects whitespaces token at beginning and end of `tokens`.

        Examples
        --------

        >>> from graphtransliterator import GraphTransliterator
        >>> gt = GraphTransliterator.from_yaml('''
        ...         tokens:
        ...             a: []
        ...             a a: []
        ...             ' ': [wb]
        ...         rules:
        ...             a: <A>
        ...             a a: <AA>
        ...         whitespace:
        ...             default: ' '
        ...             consolidate: True
        ...             token_class: wb
        ... ''')
        >>> tokens = gt.tokenize("aa")
        >>> tokens # whitespace added to ends
        [' ', 'a', 'a', ' ']
        >>> gt.match_at(1, tokens) # returns index to rule
        0
        >>> gt.rules[gt.match_at(1, tokens)] # actual rule
        TransliterationRule(production='<AA>', prev_classes=None, prev_tokens=None, tokens=['a', 'a'], next_tokens=None, next_classes=None, cost=0.41503749927884376)
        >>> gt.match_at(1, tokens, match_all=True) # index to rules, with match_all
        [0, 1]
        >>>
        >>> [gt.rules[_] for _ in gt.match_at(1, tokens, match_all=True)]
        [TransliterationRule(production='<AA>', prev_classes=None, prev_tokens=None, tokens=['a', 'a'], next_tokens=None, next_classes=None, cost=0.41503749927884376), TransliterationRule(production='<A>', prev_classes=None, prev_tokens=None, tokens=['a'], next_tokens=None, next_classes=None, cost=0.5849625007211562)]
        >>>
        """  # noqa

        graph = self._graph
        if match_all:
            matches = []
        stack = deque()

        def _append_children(node_key, token_i):
            children = None
            ordered_children = graph.node[node_key].get("ordered_children")
            if ordered_children:
                children = ordered_children.get(tokens[token_i])
                if children:
                    # reordered high to low for stack:
                    for child_key in reversed(children):
                        stack.appendleft((child_key, node_key, token_i))
                else:
                    rules_keys = ordered_children.get("__rules__")  # leafs
                    if rules_keys:
                        # There may be more than one as certain rules have
                        # constraints on them.
                        # reordered so high cost go on stack last
                        for rule_key in reversed(rules_keys):
                            stack.appendleft((rule_key, node_key, token_i))

        _append_children(0, token_i)  # append all children of root node

        while stack:  # LIFO
            node_key, parent_key, token_i = stack.popleft()
            assert token_i < len(tokens), "way past boundary"
            curr_node = graph.node[node_key]
            # check constraints on preceding edge
            if curr_node.get("accepting") and self._match_constraints(
                parent_key, node_key, token_i, tokens
            ):
                if match_all:
                    matches.append(curr_node["rule_key"])
                    continue
                else:
                    return curr_node["rule_key"]
            else:
                if token_i < len(tokens) - 1:
                    token_i += 1
                _append_children(node_key, token_i)
        if match_all:
            return matches

    def _match_tokens(
        self, start_i, c_value, tokens, check_prev=True, check_next=True, by_class=False
    ):
        """Match tokens, with boundary checks."""

        if check_prev and start_i < 0:
            return False
        if check_next and start_i + len(c_value) > len(tokens):
            return False
        for i in range(0, len(c_value)):
            if by_class:
                if not c_value[i] in self._tokens[tokens[start_i + i]]:
                    return False
            elif tokens[start_i + i] != c_value[i]:
                return False
        return True

    @property
    def graph(self):
        """`DirectedGraph`: Graph used in transliteration."""
        return self._graph

    @property
    def graphtransliterator_version(self):
        """`str`: Graph Transliterator version"""
        return self._graphtransliterator_version

    @property
    def ignore_errors(self):
        """`bool`: Ignore transliteration errors setting."""
        return self._ignore_errors

    @ignore_errors.setter
    def ignore_errors(self, value):
        self._ignore_errors = value

    @property
    def last_matched_rules(self):
        """
        `list` of `TransliterationRule`: Last transliteration rules matched.
        """
        return [self._rules[_] for _ in self._rule_keys]

    @property
    def last_matched_rule_tokens(self):
        """`list` of `list` of `str`: Last matched tokens for each rule."""
        return [self._rules[_].tokens for _ in self._rule_keys]

    @property
    def last_input_tokens(self):
        """
        `list` of `str`: Last tokenization of the input string, with whitespace
        at start and end."""
        return self._input_tokens

    @property
    def metadata(self):
        """
        `dict`: Metadata of transliterator
        """
        return self._metadata

    @property
    def onmatch_rules_lookup(self):
        """
        `dict`: On Match Rules lookup
        """
        return self._onmatch_rules_lookup

    @property
    def tokenizer_pattern(self):
        """
        `str`: Tokenizer pattern from transliterator
        """
        return self._tokenizer_pattern

    @property
    def tokens_by_class(self):
        """
        `dict` of {`str`: `list` of `str`}: Tokenizer pattern from transliterator
        """
        return self._tokens_by_class

    def transliterate(self, input):
        """
        Transliterate an input string into an output string.

        Parameters
        ----------
        input : `str`
            Input string to transliterate

        Returns
        -------
        `str`
            Transliteration output string

        Raises
        ------
        ValueError
            Cannot parse input

        Note
        ----
        Whitespace will be temporarily appended to start and end of input
        string.

        Example
        -------
        >>> from graphtransliterator import GraphTransliterator
        >>> GraphTransliterator.from_yaml(
        ... '''
        ... tokens:
        ...   a: []
        ...   ' ': [wb]
        ... rules:
        ...   a: A
        ...   ' ': '_'
        ... whitespace:
        ...   default: ' '
        ...   consolidate: True
        ...   token_class: wb
        ... ''').transliterate("a a")
        'A_A'
        """
        tokens = self.tokenize(input)  # adds initial+final whitespace
        self._input_tokens = tokens  # <--- tokens are saved here
        self._rule_keys = []
        output = ""
        token_i = 1  # adjust for initial whitespace

        while token_i < len(tokens) - 1:  # adjust for final whitespace
            rule_key = self.match_at(token_i, tokens)
            if rule_key is None:
                logger.warning(
                    "No matching transliteration rule at token pos %s of %s"
                    % (token_i, tokens)
                )
                # No parsing rule was found at this location
                if self.ignore_errors:
                    # move along if ignoring errors
                    token_i += 1
                    continue
                else:
                    raise NoMatchingTransliterationRuleException
            self._rule_keys.append(rule_key)
            rule = self.rules[rule_key]
            tokens_matched = rule.tokens
            if self._onmatch_rules:
                curr_match_rules = None
                prev_t = tokens[token_i - 1]
                curr_t = tokens[token_i]
                curr_t_rules = self._onmatch_rules_lookup.get(curr_t)
                if curr_t_rules:
                    curr_match_rules = curr_t_rules.get(prev_t)
                if curr_match_rules:
                    for onmatch_i in curr_match_rules:
                        onmatch = self._onmatch_rules[onmatch_i]
                        # <class_a> <class_a> + <class_b>
                        # a a b
                        #     ^
                        # ^      - len(onmatch.prev_rules)
                        if self._match_tokens(
                            token_i - len(onmatch.prev_classes),
                            onmatch.prev_classes,  # double checks last value
                            tokens,
                            check_prev=True,
                            check_next=False,
                            by_class=True,
                        ) and self._match_tokens(
                            token_i,
                            onmatch.next_classes,  # double checks first value
                            tokens,
                            check_prev=False,
                            check_next=True,
                            by_class=True,
                        ):
                            output += onmatch.production
                            break  # only match best onmatch rule
            output += rule.production
            token_i += len(tokens_matched)
        return output

    def tokenize(self, input):
        """
        Tokenizes an input string.

        Adds initial and trailing whitespace, which can be consolidated.

        Parameters
        ----------
        input : str
            String to tokenize

        Returns
        -------
        `list` of `str`
            List of tokens, with default whitespace token at beginning and end.

        Raises
        ------
        ValueError
            Unrecognizable input, such as a character that is not in a token

        Examples
        --------
        >>> from graphtransliterator import GraphTransliterator
        >>> t = {'ab': ['class_ab'], ' ': ['wb']}
        >>> w = {'default': ' ', 'token_class': 'wb', 'consolidate': True}
        >>> r = {'ab': 'AB', ' ': '_'}
        >>> settings = {'tokens': t, 'rules': r, 'whitespace': w}
        >>> gt = GraphTransliterator.from_easyreading_dict(settings)
        >>> gt.tokenize('ab ')
        >>> [' ', 'ab', ' ']
        """

        def is_whitespace(token):
            """Check if token is whitespace."""
            return self.whitespace.token_class in self.tokens[token]

        # start with a whitespace token
        tokens = [self.whitespace.default]

        prev_whitespace = True

        match_at = 0
        while match_at < len(input):
            match = self._tokenizer.match(input, match_at)
            if match:
                match_at = match.end()  # advance match_at
                token = match.group(0)
                # Could save match loc here:
                # matched_at = match.span(0)[0]
                if is_whitespace(token):
                    if prev_whitespace and self.whitespace.consolidate:
                        continue
                    else:
                        prev_whitespace = True
                else:
                    prev_whitespace = False
                tokens.append(token)
            else:
                logger.warning(
                    "Unrecognizable token %s at pos %s of %s"
                    % (input[match_at], match_at, input)
                )
                if not self.ignore_errors:
                    raise UnrecognizableInputTokenException
                else:
                    match_at += 1

        if self.whitespace.consolidate:
            while len(tokens) > 1 and is_whitespace(tokens[-1]):
                tokens.pop()

        tokens.append(self.whitespace.default)

        assert len(tokens) >= 2  # two whitespaces, at least

        return tokens

    def pruned_of(self, productions):
        """
        Remove transliteration rules with specific output productions.

        Parameters
        ----------
        productions : `str`, or `list` of `str`
            list of productions to remove

        Returns
        -------
        graphtransliterator.GraphTransliterator
            Graph transliterator pruned of certain productions.

        Note
        ----
        Uses original initialization parameters to construct a new
        :class:`GraphTransliterator`.

        Examples
        --------
        >>> gt = GraphTransliterator.from_yaml('''
        ...         tokens:
        ...             a: []
        ...             a a: []
        ...             ' ': [wb]
        ...         rules:
        ...             a: <A>
        ...             a a: <AA>
        ...         whitespace:
        ...             default: ' '
        ...             consolidate: True
        ...             token_class: wb
        ... ''')
        >>> gt.rules
        [TransliterationRule(production='<AA>', prev_classes=None, prev_tokens=None, tokens=['a', 'a'], next_tokens=None, next_classes=None, cost=0.41503749927884376), TransliterationRule(production='<A>', prev_classes=None, prev_tokens=None, tokens=['a'], next_tokens=None, next_classes=None, cost=0.5849625007211562)]
        >>> gt.pruned_of('<AA>').rules
        [TransliterationRule(production='<A>', prev_classes=None, prev_tokens=None, tokens=['a'], next_tokens=None, next_classes=None, cost=0.5849625007211562)]
        >>> gt.pruned_of(['<A>', '<AA>']).rules
        []
        """  # noqa
        pruned_rules = [_ for _ in self._rules if _.production not in productions]
        return GraphTransliterator(
            self._tokens,
            pruned_rules,
            self._whitespace,
            onmatch_rules=self._onmatch_rules,
            metadata=self._metadata,
            ignore_errors=self._ignore_errors,
            check_ambiguity=self._check_ambiguity,
        )

    @property
    def productions(self):
        """
        `list` of `str`: List of productions of each transliteration rule.
        """
        return [_.production for _ in self.rules]

    @property
    def tokens(self):
        """
        `dict` of {`str`:`set` of `str`}: Mappings of tokens to their classes.
        """
        return self._tokens

    @property
    def rules(self):
        """
        `list` of `TransliterationRule`: Transliteration rules sorted by cost.
        """
        return self._rules

    @property
    def onmatch_rules(self):
        """`list` of `OnMatchRules`: Rules for productions between matches."""
        return self._onmatch_rules

    @property
    def whitespace(self):
        """WhiteSpaceRules: Whitespace rules."""
        return self._whitespace

    @classmethod
    def from_dict(cls, settings, **kwargs):
        return GraphTransliterator(
            settings["tokens"],
            settings["rules"],
            settings["whitespace"],
            onmatch_rules=settings.get("onmatch_rules"),
            metadata=settings.get("metadata"),
            tokens_by_class=settings.get("tokens_by_class"),  # will be generated
            graph=settings.get("graph"),  # will be generated
            tokenizer_pattern=settings.get("tokenizer_pattern"),  # will be generated
            ignore_errors=kwargs.get("ignore_errors", False),
            check_ambiguity=kwargs.get("check_ambiguity", True),
            # **kwargs
        )

    @classmethod
    def from_easyreading_dict(cls, easyreading_settings, **kwargs):
        """
        Constructs `GraphTransliterator` from a dictionary of settings in
        "easy reading" format, i.e. the loaded contents of a YAML string.

        Parameters
        ----------
        easyreading_settings : `dict`
            Settings dictionary in easy reading format with keys:

                ``"tokens"``
                  Mappings of tokens to their classes
                  (`dict` of {str: `list` of `str`})

                ``"rules"``
                  Transliteration rules in "easy reading" format
                  (`list` of `dict` of {`str`: `str`})

                ``"onmatch_rules"``
                  On match rules in "easy reading" format
                  (`dict` of {`str`: `str`}, optional)

                ``"whitespace"``
                  Whitespace definitions, including default whitespace token,
                  class of whitespace tokens, and whether or not to consolidate
                  (`dict` of {'default': `str`, 'token_class': `str`,
                  consolidate: `bool`}, optional)

                ``"metadata"``
                  Dictionary of metadata (`dict`, optional)

        Returns
        -------
        `GraphTransliterator`

        Note
        ----
        Called by :meth:`from_yaml`.

        Example
        -------
        >>> from graphtransliterator import GraphTransliterator
        >>> tokens = {
        ...     'ab': ['class_ab'],
        ...     ' ': ['wb']
        ... }
        >>> whitespace = {
        ...     'default': ' ',
        ...     'token_class': 'wb',
        ...     'consolidate': True
        ... }
        >>> onmatch_rules = [
        ...     {'<class_ab> + <class_ab>': ','}
        ... ]
        >>> rules = {'ab': 'AB',
        ...          ' ': '_'}
        >>> settings = {'tokens': tokens,
        ...             'rules': rules,
        ...             'whitespace': whitespace,
        ...             'onmatch_rules': onmatch_rules}
        >>> gt = GraphTransliterator.from_easyreading_dict(settings)
        >>> gt.transliterate("ab abab")
        'AB_AB,AB'
        >>>

        See Also
        --------
        GraphTransliterator.yaml()
        GraphTransliterator.from_yaml_file()
        """
        # validate_easyreading_settings
        _ = EasyReadingSettingsSchema().load(easyreading_settings)
        # convert to regular settings
        _ = _process_easyreading_settings(_)
        # validate settings
        settings = SettingsSchema().load(_)
        # return GraphTransliterator
        return GraphTransliterator.from_dict(settings, **kwargs)

    @classmethod
    def from_yaml(cls, yaml_str, charnames_escaped=True, **kwargs):
        """
        Construct GraphTransliterator from a YAML str.

        Parameters
        ----------
        yaml_str : str
            YAML mappings of tokens, rules, and (optionally) onmatch_rules
        charnames_escaped : boolean
            Unescape Unicode during YAML read (default True)

        Note
        ----
        Called by :meth:`from_yaml_file` and calls :meth:`from_easyreading_dict`.

        Example
        -------
        >>> from graphtransliterator import GraphTransliterator
        >>> yaml_ = '''
        ... tokens:
        ...   a: [class1]
        ...   ' ': [wb]
        ... rules:
        ...   a: A
        ...   ' ': ' '
        ... whitespace:
        ...   default: ' '
        ...   consolidate: True
        ...   token_class: wb
        ... onmatch_rules:
        ...   - <class1> + <class1>: "+"
        ... '''
        >>> gt = GraphTransliterator.from_yaml(yaml_)
        >>> gt.transliterate("a aa")
        'A A+A'

        See Also
        --------
        GraphTransliterator.from_easyreading_dict()
        GraphTransliterator.from_yaml_file()
        """
        if charnames_escaped:
            yaml_str = _unescape_charnames(yaml_str)

        settings = yaml.safe_load(yaml_str)

        return cls.from_easyreading_dict(settings, **kwargs)

    @classmethod
    def from_yaml_file(cls, yaml_filename, **kwargs):
        """
        Construct GraphTransliterator from YAML file.

        Parameters
        ----------
        yaml_filename : str
            Name of YAML file, containing tokens, rules, and (optionally)
            onmatch_rules

        Note
        ----
        Calls :meth:`from_yaml`.

        See Also
        --------
        graphtransliterator.GraphTransliterator.from_yaml
        graphtransliterator.GraphTransliterator.from_easyreading_dict
        """
        with open(yaml_filename, "r") as f:
            yaml_string = f.read()

        return cls.from_yaml(yaml_string, **kwargs)

    def dumps(self):
        """
        Dump settings of Graph Transliterator to Javascript Object Notation (JSON).
        Returns
        -------
        str
            JSON string

        Note
        ----
        `OnmatchRule`, `TransliterationRule`, and `WhitespaceRules` are initialized from
        :meth:`collections.namedtuple`. Their keys will always be in the same order and
        can be accessed by index.

        Examples
        --------
        >>> from graphtransliterator import GraphTransliterator
        >>> yaml_ = '''
        ...   tokens:
        ...     a: [vowel]
        ...     ' ': [wb]
        ...   rules:
        ...     a: A
        ...     ' ': ' '
        ...   whitespace:
        ...     default: " "
        ...     consolidate: false
        ...     token_class: wb
        ...   onmatch_rules:
        ...     - <vowel> + <vowel>: ','  # add a comma between vowels
        ...   metadata:
        ...     author: "Author McAuthorson"
        ... '''
        >>> gt = GraphTransliterator.from_yaml(yaml_)
        >>> gt.dumps()
        '{"tokens": {"a": ["class1"], "b": ["class1"], " ": ["wb"]}, "rules": [{"production": "B2", "prev_classes": null, "prev_tokens": null, "tokens": ["a", "a"], "next_classes": null, "next_tokens": null, "cost": 0.41503749927884376}, {"production": "B", "prev_classes": null, "prev_tokens": null, "tokens": ["b"], "next_classes": null, "next_tokens": null, "cost": 0.5849625007211562}], "whitespace": {"default": " ", "token_class": "wb", "consolidate": true}, "metadata": {"author": "James Joyce"}, "ignore_errors": true, "tokens_by_class": {"class1": ["a", "b"], "wb": [" "]}, "graph": {"edge_list": [[0, 1], [1, 2], [2, 3], [0, 4], [4, 5]], "edge": {"0": {"1": {"token": "a", "cost": 0.41503749927884376}, "4": {"token": "b", "cost": 0.5849625007211562}}, "1": {"2": {"token": "a", "cost": 0.41503749927884376}}, "2": {"3": {"cost": 0.41503749927884376}}, "4": {"5": {"cost": 0.5849625007211562}}}, "node": [{"type": "Start", "ordered_children": {"a": [1], "b": [4]}}, {"type": "token", "token": "a", "ordered_children": {"a": [2]}}, {"type": "token", "token": "a", "ordered_children": {"__rules__": [3]}}, {"type": "rule", "rule_key": 0, "rule": ["B2", null, null, ["a", "a"], null, null, 0.41503749927884376], "accepting": true, "ordered_children": {}}, {"type": "token", "token": "b", "ordered_children": {"__rules__": [5]}}, {"type": "rule", "rule_key": 1, "rule": ["B", null, null, ["b"], null, null, 0.5849625007211562], "accepting": true, "ordered_children": {}}]}, "tokenizer_pattern": "(a|b|\\\\ )", "graphtransliterator_version": "0.2.14"}'
                     ('graphtransliterator_version', '0.2.14')])
        See Also
        --------
        dump: Dump GraphTransliterator configuration to Python types
        """  # noqa
        return GraphTransliteratorSchema().dumps(self)

    def dump(self):
        """
        Dump configuration of Graph Transliterator to Python types.

        Returns
        -------
        OrderedDict
            GraphTransliterator configuration as a dictionary with keys:

                ``"graph"``
                  Serialization of `DirectedGraph`
                  (`dict`)

                ``"tokenizer_pattern"``
                  Regular expression for tokenizing
                  (`str`)

                ``"tokens"``
                  Mappings of tokens to their classes
                  (`dict` of {str: `list` of `str`})

                ``"rules"``
                  Transliteration rules in direct format
                  (`list` of `dict` of {`str`: `str`})

                ``"onmatch_rules"``
                  Onmatch settings
                  (`list` of `OnMatchRule`)

                ``"onmatch_rules_lookup"``
                  Dictionary keyed by current token to previous token
                  containing a list of indexes of applicable `OnmatchRule`
                  to try
                  (`dict` of {`str`: `dict` of {`str`: `list` of `int`}})

                ``"whitespace"``
                  Whitespace settings
                  (`WhitespaceRules`)

                ``"metadata"``
                  Dictionary of metadata (`dict`)

                ``"graphtransliterator_version"``
                  Module version of `graphtransliterator` (`str`)

        Example
        -------
        >>> from graphtransliterator import GraphTransliterator
        >>> yaml_ = '''
        ...   tokens:
        ...     a: [vowel]
        ...     ' ': [wb]
        ...   rules:
        ...     a: A
        ...     ' ': ' '
        ...   whitespace:
        ...     default: " "
        ...     consolidate: false
        ...     token_class: wb
        ...   onmatch_rules:
        ...     - <vowel> + <vowel>: ','  # add a comma between vowels
        ...   metadata:
        ...     author: "Author McAuthorson"
        ... '''
            >>> gt = GraphTransliterator.from_yaml(yaml_)
            >>> gt.dump()
            OrderedDict([('tokens', {'a': ['class1'], 'b': ['class1'], ' ': ['wb']}),
             ('rules',
              [OrderedDict([('production', 'B2'),
                            ('prev_classes', None),
                            ('prev_tokens', None),
                            ('tokens', ['a', 'a']),
                            ('next_classes', None),
                            ('next_tokens', None),
                            ('cost', 0.41503749927884376)]),
               OrderedDict([('production', 'B'),
                            ('prev_classes', None),
                            ('prev_tokens', None),
                            ('tokens', ['b']),
                            ('next_classes', None),
                            ('next_tokens', None),
                            ('cost', 0.5849625007211562)])]),
             ('whitespace',
              OrderedDict([('default', ' '),
                           ('token_class', 'wb'),
                           ('consolidate', True)])),
             ('metadata', {'author': 'James Joyce'}),
             ('ignore_errors', True),
             ('tokens_by_class', {'class1': ['a', 'b'], 'wb': [' ']}),
             ('graph',
              {'edge_list': [(0, 1), (1, 2), (2, 3), (0, 4), (4, 5)],
               'edge': {0: {1: {'token': 'a', 'cost': 0.41503749927884376},
                 4: {'token': 'b', 'cost': 0.5849625007211562}},
                1: {2: {'token': 'a', 'cost': 0.41503749927884376}},
                2: {3: {'cost': 0.41503749927884376}},
                4: {5: {'cost': 0.5849625007211562}}},
               'node': [{'type': 'Start',
                 'ordered_children': {'a': [1], 'b': [4]}},
                {'type': 'token',
                 'token': 'a',
                 'ordered_children': {'a': [2]}},
                {'type': 'token',
                 'token': 'a',
                 'ordered_children': {'__rules__': [3]}},
                {'type': 'rule',
                 'rule_key': 0,
                 'rule': TransliterationRule(production='B2', prev_classes=None, prev_tokens=None, tokens=['a', 'a'], next_tokens=None, next_classes=None, cost=0.41503749927884376),
                 'accepting': True,
                 'ordered_children': {}},
                {'type': 'token',
                 'token': 'b',
                 'ordered_children': {'__rules__': [5]}},
                {'type': 'rule',
                 'rule_key': 1,
                 'rule': TransliterationRule(production='B', prev_classes=None, prev_tokens=None, tokens=['b'], next_tokens=None, next_classes=None, cost=0.5849625007211562),
                 'accepting': True,
                 'ordered_children': {}}]}),
             ('tokenizer_pattern', '(a|b|\\ )'),
             ('graphtransliterator_version', '0.2.14')])
        See Also
        --------
        dump: Dump GraphTransliterator settings to Javascript Object Notation (JSON) str
"""  # noqa
        return GraphTransliteratorSchema().dump(self)

    @staticmethod
    def load(settings, **kwargs):
        """Create GraphTransliterator from settings as Python data types."""
        return GraphTransliteratorSchema().load(settings, **kwargs)

    @staticmethod
    def loads(settings, **kwargs):
        """Create GraphTransliterator from JSON settings."""
        return GraphTransliteratorSchema().loads(settings, **kwargs)

    def check_for_ambiguity(self):
        """
        Check if multiple transliteration rules could match the same tokens.

        This function first groups the transliteration rules by number of
        tokens. It then checks to see if any pair of the same cost would match
        the same sequence of tokens. If so, it finally checks if a less costly
        rule would match those particular sequences. If not, there is
        ambiguity.

        Details of all ambiguity are sent in a :func:`logging.warning`.

        Note
        ----
        Called during initialization if ``check_ambiguity`` is set.

        Raises
        ------
        AmbiguousTransliterationRulesException
            Multiple transliteration rules could match the same tokens.

        Example
        -------
        >>> from graphtransliterator import GraphTransliterator
        >>> yaml_filename = '''
        ... tokens:
        ...   a: [class1, class2]
        ...   ' ': [wb]
        ... rules:
        ...   <class1> a: AW
        ...   <class2> a: AA # ambiguous rule
        ... whitespace:
        ...   default: ' '
        ...   consolidate: True
        ...   token_class: wb
        ... '''
        >>> gt = GraphTransliterator.from_yaml(yaml_, check_ambiguity=False)
        >>> gt.check_for_ambiguity()
        WARNING:root:The pattern [{'a'}, {'a'}] can be matched by both:
          <class1> a
          <class2> a
        ...
        graphtransliterator.exceptions.AmbiguousTransliterationRulesException
        >>>
        """

        ambiguity = False

        all_tokens = set(self.tokens.keys())

        rules = self._rules

        if not rules:
            return True

        max_prev = [_count_of_prev(rule) for rule in rules]
        global_max_prev = max(max_prev)
        max_curr_next = [_count_of_curr_and_next(rule) for rule in rules]
        global_max_curr_next = max(max_curr_next)

        # Generate a matrix of rules, where width is the max of
        # any previous tokens/classes + max of current/next tokens/classes.
        # Each rule's specifications starting from the max of the previous
        # tokens/classes. Other positions are filled by the set of all possible
        # tokens.

        matrix = []

        width = global_max_prev + global_max_curr_next

        for i, rule in enumerate(rules):
            row = [all_tokens] * (global_max_prev - max_prev[i])
            row += _tokens_possible(rule, self._tokens_by_class)
            row += [all_tokens] * (width - len(row))
            matrix += [row]

        def full_intersection(i, j):
            """ Intersection of  matrix[i] and matrix[j], else None."""

            intersections = []
            for k in range(width):
                intersection = matrix[i][k].intersection(matrix[j][k])
                if not intersection:
                    return None
                intersections += [intersection]
            return intersections

        def covered_by(intersection, row):
            """Check if intersection is covered by row."""
            for i in range(len(intersection)):
                diff = intersection[i].difference(row[i])
                if diff:
                    return False
            return True

        # Iterate through rules based on number of tokens (cost).
        # If there are ambiguities, then see if a less costly rule
        # would match the rule. If it does not, there is ambiguity.

        grouper = lambda x: (_count_of_tokens(x))  # noqa, could replace by cost

        for group_val, group_iter in itertools.groupby(
            enumerate(self._rules), key=lambda x: grouper(x[1])
        ):

            group = list(group_iter)
            if len(group) == 1:
                continue
            for i in range(len(group) - 1):
                for j in range(i + 1, len(group)):
                    i_index = group[i][0]
                    j_index = group[j][0]
                    intersection = full_intersection(i_index, j_index)
                    if not intersection:
                        break

                    # Check if a less costly rule matches intersection

                    def covered_by_less_costly():
                        for r_i, rule in enumerate(rules):
                            if r_i in (i_index, j_index):
                                continue
                            if rule.cost > rules[i_index].cost:
                                continue
                            rule_tokens = matrix[r_i]
                            if covered_by(intersection, rule_tokens):
                                return True
                        return False

                    if not covered_by_less_costly():
                        logging.warning(
                            "The pattern {} can be matched by both:\n"
                            "  {}\n"
                            "  {}\n".format(
                                intersection,
                                _easyreading_rule(rules[i_index]),
                                _easyreading_rule(rules[j_index]),
                            )
                        )
                        ambiguity = True
        if ambiguity:
            raise AmbiguousTransliterationRulesException


def _easyreading_rule(rule):
    """Get an easy-reading string of a rule."""

    def _token_str(x):
        return " ".join(x)

    def _class_str(x):
        return " ".join(["<%s>" % _ for _ in x])

    out = ""
    if rule.prev_classes and rule.prev_tokens:
        out = "({} {}) ".format(
            _class_str(rule.prev_classes), _token_str(rule.prev_tokens)
        )
    elif rule.prev_classes:
        out = "{} ".format(_class_str(rule.prev_classes))
    elif rule.prev_tokens:
        out = "({}) ".format(_token_str(rule.prev_tokens))

    out += _token_str(rule.tokens)

    if rule.next_tokens and rule.next_classes:
        out += " ({} {})".format(
            _token_str(rule.next_tokens), _class_str(rule.next_classes)
        )
    elif rule.next_tokens:
        out += " ({})".format(_token_str(rule.next_tokens))
    elif rule.next_classes:
        out += " {}".format(_class_str(rule.next_classes))
    return out


def _count_of_prev(rule):
    """Count previous tokens to be present before a match in a rule."""

    return len(rule.prev_classes or []) + len(rule.prev_tokens or [])


def _count_of_curr_and_next(rule):
    """Count tokens to be matched and those to follow them in rule."""

    return len(rule.tokens) + len(rule.next_tokens or []) + len(rule.next_classes or [])


def _count_of_tokens(rule):
    return (
        len(rule.prev_classes or [])
        + len(rule.prev_tokens or [])
        + len(rule.tokens)
        + len(rule.next_tokens or [])
        + len(rule.next_classes or [])
    )


def _prev_tokens_possible(rule, tokens_by_class):
    """`list` of set of possible preceding tokens for a rule."""

    return [tokens_by_class[_] for _ in rule.prev_classes or []] + [
        set([_]) for _ in rule.prev_tokens or []
    ]


def _curr_and_next_tokens_possible(rule, tokens_by_class):
    """`list` of sets of possible current and following tokens for a rule."""

    return (
        [set([_]) for _ in rule.tokens]
        + [set([_]) for _ in rule.next_tokens or []]
        + [tokens_by_class[_] for _ in rule.next_classes or []]
    )


def _tokens_possible(row, tokens_by_class):
    """`list` of sets of possible tokens matched for a rule."""

    return _prev_tokens_possible(row, tokens_by_class) + _curr_and_next_tokens_possible(
        row, tokens_by_class
    )


# Initialization-related functions for unescaping Unicode


def _unescape_charnames(input_str):
    r"""
    Convert \\N{Unicode charname}-escaped str to unicode characters.

    This is useful for specifying exact character names, and a default
    escape feature in Python that needs a function to be used for reading
    from files.

    Parameters
    ----------
    input_str : str
        The unescaped string, with \\N{Unicode charname} converted to
        the corresponding Unicode characters.

    Examples
    --------

    >>> from graphtransliterator import GraphTransliterator
    >>> GraphTransliterator._unescape_charnames(r"H\N{LATIN SMALL LETTER I}")
    'Hi'
    """

    def get_unicode_char(matchobj):
        """Get Unicode character value from escaped character sequences."""
        charname = matchobj.group(0)
        match = re.match(r"\\N{([A-Z ]+)}", charname)
        char = unicodedata.lookup(match.group(1))  # KeyError if invalid
        return char

    return re.sub(r"\\N{[A-Z ]+}", get_unicode_char, input_str)
