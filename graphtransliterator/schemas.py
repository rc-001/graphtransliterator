from marshmallow import (
    fields,
    post_load,
    post_dump,
    Schema,
    validate,
    ValidationError,
    validates_schema,
)
from collections import defaultdict
from .graphs import DirectedGraph
from .initialize import _onmatch_rule_of, _transliteration_rule_of, _whitespace_rules_of
from .process import RULE_RE, ONMATCH_RE
from .rules import TransliterationRule


class WhitespaceDictSettingsSchema(Schema):
    """Schema for Whitespace definition as a `dict`."""

    default = fields.Str(required=True)
    token_class = fields.Str(required=True)
    consolidate = fields.Boolean(required=True)


class WhitespaceSettingsSchema(WhitespaceDictSettingsSchema):
    """Schema for Whitespace definition that loads as `WhitespaceRules.`"""

    @post_load
    def make_whitespace_rules(self, data, **kwargs):
        return _whitespace_rules_of(data)


class EasyReadingSettingsSchema(Schema):
    """Schema for easy reading settings.

    Provides initial validation based on easy reading format.
    """

    tokens = fields.Dict(
        keys=fields.Str(), values=fields.List(fields.Str()), required=True
    )
    rules = fields.Dict(
        keys=fields.Str(validate=validate.Regexp(RULE_RE)),
        values=fields.Str(),
        required=True,
    )
    onmatch_rules = fields.List(
        fields.Dict(
            keys=fields.Str(validate=validate.Regexp(ONMATCH_RE)),
            values=fields.Str(),
            required=False,
        )
    )
    metadata = fields.Dict(
        keys=fields.Str(),
        # no restriction on values
        required=False,
    )
    whitespace = fields.Nested(WhitespaceDictSettingsSchema)


class TransliterationRuleSchema(Schema):
    """Schema for TransliterationRule."""

    production = fields.Str(required=True)
    tokens = fields.List(fields.Str(), required=True)
    prev_classes = fields.List(fields.Str(), allow_none=True)
    next_classes = fields.List(fields.Str(), allow_none=True)
    prev_tokens = fields.List(fields.Str(), allow_none=True)
    next_tokens = fields.List(fields.Str(), allow_none=True)

    class Meta:
        fields = (
            "production",
            "prev_classes",
            "prev_tokens",
            "tokens",
            "next_classes",
            "next_tokens",
            "cost",
        )
        ordered = True

    @post_load
    def make_transliteration_rule(self, data, **kwargs):
        return _transliteration_rule_of(data)


class OnMatchRuleSchema(Schema):
    """Schema for OnMatchRule."""

    prev_classes = fields.List(fields.Str())
    next_classes = fields.List(fields.Str())
    production = fields.Str()

    class Meta:
        fields = ("prev_classes", "next_classes", "production")
        ordered = True

    @post_load
    def make_onmatch_rule(self, data, **kwargs):
        return _onmatch_rule_of(data)


class SettingsSchema(Schema):
    """Schema for settings in dictionary format.

    Performs validation.
    """

    tokens = fields.Dict(
        keys=fields.Str(), values=fields.List(fields.Str()), required=True
    )
    rules = fields.Nested(TransliterationRuleSchema, many=True, required=True)
    whitespace = fields.Nested(WhitespaceSettingsSchema, many=False, required=True)
    metadata = fields.Dict(
        keys=fields.Str(), required=False  # no restriction on values
    )
    onmatch_rules = fields.Nested(OnMatchRuleSchema, many=True, required=False)

    @post_load
    def sort_rules_by_cost(self, data, **kwargs):
        """Sort rules by cost."""
        data["rules"] = sorted(data["rules"], key=lambda rule: rule.cost)
        return data

    @post_load
    def token_classes_to_sets(self, data, **kwargs):
        data["tokens"] = {k: set(v) for k, v in data["tokens"].items()}
        return data

    @validates_schema
    def validate_token_classes(self, data, **kwargs):
        errors = defaultdict(list)
        token_classes = list(set().union(*data["tokens"].values()))

        # validate onmatch_rules and rules
        for rule_type in ("onmatch_rules", "rules"):
            for rule in data[rule_type]:
                for property in ("prev_classes", "next_classes"):
                    values = getattr(rule, property)
                    if not values:
                        continue
                    for _ in values:
                        if _ not in token_classes:
                            errors[rule_type].append(
                                'Invalid token class "{}" in {} of {}'.format(
                                    _, property, rule
                                )
                            )

        # validate whitespace token_class
        whitespace = data["whitespace"]
        whitespace_token_class = whitespace.token_class
        if whitespace_token_class not in token_classes:
            errors["whitespace"].append(
                'Invalid token class "{}" in whitespace.'.format(
                    whitespace_token_class, whitespace
                )
            )
        if errors:
            raise ValidationError(dict(errors))

    @validates_schema
    def validate_tokens(self, data, **kwargs):
        errors = defaultdict(list)
        token_types = data["tokens"].keys()

        # validate whitespace
        whitespace = data["whitespace"]
        default_whitespace = whitespace.default
        if default_whitespace not in token_types:
            errors["whitespace"].append(
                'Invalid default token "{}" in whitespace.'.format(default_whitespace)
            )

        # validate rules
        rules = data["rules"]
        for rule in rules:
            for property in ("tokens", "prev_tokens", "next_tokens"):
                values = getattr(rule, property)
                if not values:
                    continue
                for _ in values:
                    if _ not in token_types:
                        errors["rules"].append(
                            'Invalid token "{}" in {} of rule {}'.format(
                                _, property, rule
                            )
                        )
        if errors:
            raise ValidationError(dict(errors))


class DirectedGraphSchema(Schema):
    """ Schema for DirectedGraph.

    Does not rigorously validate graph.
    """

    class Meta:
        fields = ("node", "edge", "edge_list")

    @post_dump
    def dict_of_rule(self, data, **kwargs):
        # make TransliterationRule a dict
        for node in data["node"]:
            rule = node.get("rule")
            if rule:
                if type(rule) == TransliterationRule:
                    node["rule"] = rule._asdict()
        return data

    @post_load
    def make_graph(self, data, **kwargs):
        # adjust TransliterationRule
        for node in data["node"]:
            rule = node.get("rule")
            if rule:
                node["rule"] = TransliterationRule(**rule)
        return DirectedGraph(**data)
