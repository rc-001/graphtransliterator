# -*- coding: utf-8 -*-

"""Top-level package for Graph Transliterator."""

__author__ = """A. Sean Pue"""
__email__ = 'pue@msu.edu'
__version__ = '0.1.1'

from .graphtransliterator import GraphTransliterator  # noqa
# the following line prevents
# 'graphtransliterator.graphtralisterator.GraphTransliterator
# as object name
GraphTransliterator.__module__ = "graphtransliterator"
