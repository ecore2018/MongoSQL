"""
MongoSQL parser

Example supported queries:

SELECT {fields:SYMBOL_LIST}
FROM {collection:SYMBOL}
WHERE {condition:CMP_EXPRESSION_LIST}
SKIP {skip:INTEGER}
LIMIT {limit:INTEGER}
SORT {sort:SORT_LIST}

->  db['{collection}'].find(
        {condition}, fields={fields}, limit={limit},
        skip={skip}, sort={sort})


#=== todo: aggregation queries

"""

import os
from collections import namedtuple

import ply.yacc as yacc

from mongosql.lexer import lexer, tokens  # NOQA
from mongosql.support import (
    Symbol, Map, SelectOperation, Expression, Operation, Comparison,
    LogicalAnd, LogicalOr, LogicalNot, FunctionCall, AggregateOperation,
    AggregateCmdProject)


def p_error(p):
    raise Exception("Parser error!", p)

named_expression = namedtuple('named_expression', ('name', 'expression'))


##----------------------------------------------------------------------------
## Statements
## This must be on top, as it works as the "base" for the parsing
## grammar.
##----------------------------------------------------------------------------


def p_statement(p):
    """
    statement : expression
              | operation
    """
    p[0] = p[1]


def p_operation(p):
    """
    operation : operation_select
              | operation_aggregate
    """
    p[0] = p[1]


##----------------------------------------------------------------------------
## Parsing of simple expressions
##
## We have
## - base types
## - symbols
## - <expr> <operator> <expr>
## - <expr> <comparator> <expr>
## - ( <expr> )  -> takes high precedence
## - <expr> AND|OR <expr>
## - NOT <expr>
##----------------------------------------------------------------------------

def p_expression_in_parens(p):
    """expression : LPAREN expression RPAREN"""
    p[0] = p[2]


def p_expression_base_type(p):
    """expression : base_type"""
    p[0] = p[1]


def p_expression_symbol(p):
    """expression : SYMBOL"""
    p[0] = Symbol(p[1])


def p_expression_operation(p):
    """
    expression : expression PLUS expression
               | expression MINUS expression
               | expression STAR expression
               | expression SLASH expression
               | expression PERCENT expression
    """
    p[0] = Operation(first=p[1], operator=p[2], second=p[3])


def p_expression_comparison(p):
    """
    expression : expression LT expression
               | expression LTE expression
               | expression GT expression
               | expression GTE expression
               | expression DBLEQUAL expression
               | expression NE expression
    """
    p[0] = Comparison(first=p[1], operator=p[2], second=p[3])


def p_expression_logical_and(p):
    """expression : expression AND expression"""
    p[0] = LogicalAnd(p[1], p[3])


def p_expression_logical_or(p):
    """expression : expression OR expression"""
    p[0] = LogicalOr(p[1], p[3])


def p_expression_not(p):
    """expression : NOT expression"""
    p[0] = LogicalNot(p[1])


##----------------------------------------------------------------------------
## Function call
##----------------------------------------------------------------------------

def p_expression_call(p):
    """
    expression : SYMBOL LPAREN expression_list RPAREN
               | SYMBOL LPAREN RPAREN
    """
    args = p[3] if (len(p) == 5) else []
    p[0] = FunctionCall(p[1], args)


##----------------------------------------------------------------------------
## Expression lists
##----------------------------------------------------------------------------

def p_expression_list_one(p):
    """expression_list : expression"""
    p[0] = [p[1]]


def p_expression_list(p):
    """expression_list : expression_list COMMA expression"""
    p[0] = p[1]
    p[0].append(p[3])


##----------------------------------------------------------------------------
## Named espressions:
##
##     name = expression
##     expression AS name
##----------------------------------------------------------------------------

def p_named_expression_as(p):
    """named_expression : expression AS SYMBOL"""
    p[0] = named_expression(p[3], p[1])


def p_named_expression(p):
    """named_expression : SYMBOL EQUAL expression"""
    p[0] = named_expression(p[1], p[3])


def p_named_expression_list_one(p):
    """named_expression_list : named_expression"""
    assert isinstance(p[1], named_expression)
    p[0] = [p[1]]


def p_named_expression_list(p):
    """named_expression_list : named_expression_list COMMA named_expression"""
    assert isinstance(p[3], named_expression)
    p[0] = p[1]
    p[0].append(p[3])


##----------------------------------------------------------------------------
## Aggregation framework
##----------------------------------------------------------------------------

def p_operation_aggregate(p):
    """
    operation_aggregate : AGGREGATE SYMBOL
    """
    assert isinstance(p[2], basestring)
    p[0] = AggregateOperation(collection=p[2])


def p_operation_aggregate_project(p):
    """
    operation_aggregate : operation_aggregate PROJECT named_expression_list
    """
    assert all(isinstance(x, named_expression) for x in p[3])
    p[0] = p[1]
    p[0].pipeline.append(AggregateCmdProject(p[3]))


##----------------------------------------------------------------------------
## The SELECT query:
##
## SELECT <fields_spec>
## FROM <collection>
## WHERE <expression>
## LIMIT <int>
## SKIP <int>
## SORT <sort_spec>
##----------------------------------------------------------------------------

def p_operation_select_base(p):
    """operation_select : SELECT fields_spec FROM SYMBOL"""
    assert (p[2] is None) or isinstance(p[2], (list, tuple))
    assert isinstance(p[4], basestring)
    p[0] = SelectOperation(collection=p[4], fields=p[2])


def p_operation_select_condition(p):
    """operation_select : operation_select WHERE expression"""
    p[0] = p[1]
    assert isinstance(p[0], SelectOperation)
    assert isinstance(p[3], Expression)
    p[0].query = p[3]


def p_operation_select_limit(p):
    """operation_select : operation_select LIMIT INTEGER"""
    p[0] = p[1]
    assert isinstance(p[0], SelectOperation)
    assert isinstance(p[3], (int, long))
    p[0].limit = p[3]


def p_operation_select_skip(p):
    """operation_select : operation_select SKIP INTEGER"""
    p[0] = p[1]
    assert isinstance(p[0], SelectOperation)
    assert isinstance(p[3], (int, long))
    p[0].skip = p[3]


def p_operation_select_sort(p):
    """operation_select : operation_select SORT sort_spec"""
    p[0] = p[1]
    assert isinstance(p[0], SelectOperation)
    assert isinstance(p[3], (list, tuple))
    p[0].sort = dict(p[3])


##----------------------------------------------------------------------------
## Field names specification.
## Can be "*" or "name, name1, name2"
## Aliasing is currently not supported (name AS other, name1 AS other1, ..)
##----------------------------------------------------------------------------

def p_fields_spec_star(p):
    """fields_spec : STAR"""
    p[0] = None


def p_fields_spec_names(p):
    """fields_spec : symbol_list"""
    p[0] = p[1]


##----------------------------------------------------------------------------
## List of symbols
##----------------------------------------------------------------------------

def p_symbol_list_one(p):
    """symbol_list : SYMBOL"""
    p[0] = [p[1]]


def p_symbol_list(p):
    """symbol_list : symbol_list COMMA SYMBOL"""
    p[0] = p[1]
    p[1].append(p[3])


##----------------------------------------------------------------------------
## Sort specification
## field, field1 ASC, field2 DESC
## -> [(field, 1), (field1, 1), (field2, -1)]
##----------------------------------------------------------------------------

def p_sort_direction_default(p):
    """sort_direction :"""
    p[0] = 1


def p_sort_direction_asc(p):
    """sort_direction : ASC"""
    p[0] = 1


def p_sort_direction_desc(p):
    """sort_direction : DESC"""
    p[0] = -1


def p_sort_spec_item(p):
    """sort_spec_item : SYMBOL sort_direction"""
    p[0] = (p[1], p[2])


def p_sort_spec_one(p):
    """sort_spec : sort_spec_item"""
    p[0] = [p[1]]


def p_sort_spec_list(p):
    """sort_spec : sort_spec COMMA sort_spec_item"""
    p[0] = p[1]
    p[1].append(p[3])


##----------------------------------------------------------------------------
## Base types
##----------------------------------------------------------------------------

def p_base_type(p):
    """
    base_type : string
              | INTEGER
              | FLOAT
              | TRUE
              | FALSE
              | NULL
              | map
    """
    p[0] = p[1]


def p_string(p):
    """string : STRING"""
    assert p[1][0] == p[1][-1]
    assert p[1][0] in '\'"'
    p[0] = p[1][1:-1]  # todo: replace escapes


def p_map_empty(p):
    """map : LBRACE RBRACE"""
    p[0] = Map()


def p_map(p):
    """
    map : LBRACE named_expression_list RBRACE
        | LBRACE named_expression_list COMMA RBRACE
    """
    p[0] = Map((i.name, i.expression) for i in p[2])


debug = True if os.environ.get('MONGOSQL_DEBUG') else False
parser = yacc.yacc(debug=debug)
