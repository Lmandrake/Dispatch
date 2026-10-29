# Tally language specification, version 1.0

Tally is a small dynamically typed scripting language. This document is the
complete and normative definition of the language and of the Python package
`tally` that implements it. Where an example and the prose disagree, the
prose wins (they should not disagree).

## 1. The Python interface

```python
from tally import run
out = run(source)          # source: str, the whole program
```

- `run(source)` parses the entire program first, then executes it, and
  returns everything the program printed, as one string. Every call to
  `run` is independent: fresh global scope, fresh output buffer.
- If the program has a syntax error (section 9.1), nothing is executed and
  `run` raises `TallySyntaxError`.
- If a runtime error occurs (section 9.2), execution stops and `run`
  raises the corresponding exception. The exception's `output` attribute
  holds everything printed before the error, exactly as `run` would have
  returned it. A `print` call whose arguments fail to evaluate prints
  nothing.
- The exception classes live in `tally.errors` and are re-exported from
  `tally`. They are already written; do not change their constructors or
  their `__str__`.
- `python3 -m tally FILE` runs the program in FILE (UTF-8). Output goes to
  stdout. On an error, the output produced so far is written to stdout,
  then one line `<ClassName>: <str(exc)>` is written to stderr, and the
  exit status is 1. Otherwise the exit status is 0.

Python's own exceptions (including `RecursionError`) must never escape
from `run` for any program, valid or not, that this specification gives a
meaning to.

## 2. Lexical structure

Source text is a sequence of Unicode characters. Lines are separated by
`\n` only. Positions are reported as a 1-based line number and a 1-based
column number, where the column counts characters (a tab is one
character).

Whitespace (space, tab, carriage return, newline) separates tokens and is
otherwise ignored. A `#` outside a string starts a comment that runs to the
end of the line.

### 2.1 Identifiers and keywords

An identifier matches `[A-Za-z_][A-Za-z0-9_]*`. The following are
keywords and cannot be used as identifiers:

```
let fn if elif else while break continue return true false nil and or not
```

### 2.2 Number literals

- Integer literal: one or more ASCII digits, e.g. `0`, `42`, `007` (leading
  zeros are allowed and ignored).
- Decimal literal: one or more digits, a `.`, one or more digits, e.g.
  `2.50`. It denotes the exact rational value of the written decimal
  (`0.1` is exactly one tenth). There is no exponent notation.
- A `.` that is not between two digits is not part of a number; since `.`
  is not a token on its own, it is then an unexpected character
  (so `1.` and `.5` are syntax errors).
- There are no negative literals; `-5` is unary minus applied to `5`.

### 2.3 String literals

Strings are enclosed in double quotes. A raw newline may not appear inside
a string. The escape sequences are:

| escape | meaning |
|---|---|
| `\n` | newline |
| `\t` | tab |
| `\\` | backslash |
| `\"` | double quote |
| `\u{H...}` | the code point given by 1 to 6 hex digits (either case), at most `10FFFF` |

Errors (all `TallySyntaxError`). The characters of a string are examined
in order and the first problem found is the one reported, so `"a\q` with
no closing quote reports the invalid escape.

- A string not closed before a newline or the end of input:
  `unterminated string`, reported at the opening quote.
- A backslash followed by any other character: `invalid escape sequence '\X'`
  where X is that character, reported at the backslash. (If the backslash is
  the last character before a newline or the end of input, the error is
  `unterminated string` instead.)
- A `\u` not followed by `{`, 1-6 hex digits and `}`, or whose value is
  above `10FFFF`: `invalid unicode escape`, reported at the backslash.

### 2.4 Operators and punctuation

```
+  -  *  /  //  %  **  ==  !=  <  <=  >  >=  =  (  )  [  ]  {  }  ,  ;  :
```

The lexer always takes the longest operator that matches (`**` before `*`,
`//` before `/`, `==` before `=`, `<=` before `<`). Any other character
outside a string or comment, including a lone `!` or `.`, is a syntax
error `unexpected character 'X'` reported at that character.

## 3. Values and types

Every value has exactly one type. The built-in `type(v)` returns the type
name as a string.

| type name | values |
|---|---|
| `int` | integers of unlimited size |
| `rat` | exact rational numbers that are not integers |
| `str` | immutable sequences of Unicode code points |
| `bool` | `true`, `false` |
| `nil` | `nil` |
| `list` | mutable sequences of values |
| `function` | user-defined functions and built-in functions |

`int` and `rat` together are the *numbers*. Numbers are always normalized:
any arithmetic result, and any decimal literal, whose value is an integer
is an `int`. So `2.0`, `6 / 3` and `3 * (1 / 3)` are all the `int` values
`2`, `2` and `1`, and `type(1.0)` is `"int"`. Arithmetic is exact; there is
no floating point anywhere in Tally.

`bool` is not a number: `true + 1` is a type error and `true == 1` is
`false`.

### 3.1 Truthiness

`false`, `nil`, `0`, `""` and `[]` (an empty list) are *falsy*. Every other
value, including every function, is *truthy*.

## 4. Display form

`print` and `str` convert values to text using the *display form*:

- `int`: decimal digits, with a leading `-` if negative.
- `rat`: if the denominator (in lowest terms) has no prime factors other
  than 2 and 5, the exact finite decimal with the fewest digits after the
  point, with at least one digit before the point: `1/8` is `0.125`,
  `-5/2` is `-2.5`, `1/20` is `0.05`. Otherwise `N/D` in lowest terms with
  any minus sign on N: `1/3`, `-7/6`.
- `str`: the characters themselves, without quotes.
- `bool`: `true` or `false`. `nil`: `nil`.
- `list`: `[`, the elements' *nested forms* separated by `, ` (comma and
  space), then `]`. The empty list is `[]`.
- user function: `<fn NAME>` for a function created by a `fn NAME(...)`
  declaration, `<fn>` for one created by a function expression (even if
  it was then stored in a variable).
- built-in function: `<builtin NAME>`, e.g. `<builtin len>`.

The *nested form* (used only for list elements) is the display form,
except that a `str` is written in double quotes with these characters
escaped: backslash as `\\`, double quote as `\"`, newline as `\n`, tab as
`\t`; all other characters appear as themselves. A list that contains
itself, directly or indirectly, is displayed with `[...]` in place of any
list that is already being displayed further out, e.g. after
`let a = [1]; push(a, a);`, `a` displays as `[1, [...]]`.

## 5. Expressions

### 5.1 Precedence

From lowest to highest binding:

| level | operators | associativity |
|---|---|---|
| 1 | `or` | left |
| 2 | `and` | left |
| 3 | `not` (prefix) | — |
| 4 | `==` `!=` `<` `<=` `>` `>=` | chained (5.4) |
| 5 | `+` `-` | left |
| 6 | `*` `/` `//` `%` | left |
| 7 | `-` (prefix, unary minus) | — |
| 8 | `**` | right |
| 9 | call `f(...)`, index `x[i]`, slice `x[a:b]` (postfix) | left |

The right operand of `**` is a level-7 expression, so `2 ** -1` is allowed
and is `0.5`. Consequences: `-2 ** 2` is `-4`; `(-2) ** 2` is `4`;
`2 ** 3 ** 2` is `512`; `2 ** -2 ** 2` is `2 ** (-(2 ** 2))`, i.e. `1/16`;
`--3` is `3`; `not 1 == 2` is `not (1 == 2)`.

Primary expressions are: number, string, `true`, `false`, `nil`, an
identifier, a parenthesized expression, a list literal
`[e1, e2, ...]` (an optional trailing comma is allowed after at least one
element; `[,]` is an error), and a function expression (section 7).

### 5.2 Evaluation order

Operands are evaluated left to right; for a call, the callee is evaluated
first and then the arguments left to right; for an index or slice, the
object first, then the index or bounds left to right.

### 5.3 Arithmetic

- `+`, `-`, `*` on two numbers: the exact result.
- `/` on two numbers: the exact quotient.
- `//` on two numbers: the floor (toward negative infinity) of the exact
  quotient; always an `int`. `-7 // 2` is `-4`; `7.5 // 2` is `3`.
- `%` on two numbers: `a - b * (a // b)`, so the result has the sign of
  `b` (or is 0). `-7 % 3` is `2`, `7 % -3` is `-2`, `7.5 % 2` is `1.5`.
- `/`, `//`, `%` with a zero right operand: `TallyZeroDivisionError`
  `division by zero`.
- `a ** b`: `b` must be an `int` (if both operands are numbers but `b` is
  a `rat`, `TallyTypeError` `exponent must be an int`). For `b >= 0` the
  exact power (`0 ** 0` is `1`); for `b < 0`, `1 / (a ** -b)`, which for
  `a == 0` is `TallyZeroDivisionError` `division by zero`.
- Unary `-` on a number negates it.
- `+` on two strings concatenates; on two lists, makes a new list with the
  elements of both.
- `*` with a `str` or `list` on one side and an `int` on the other (either
  order) repeats it, producing a new value; a count of 0 or less gives an
  empty string or list.
- Any other operand types for `+ - * / // % **`: `TallyTypeError`
  `unsupported operand types for OP: 'T1' and 'T2'` using the operator
  text and the two type names. For unary minus: `bad operand type for
  unary -: 'T'`. (An `int` count with a `str` is fine; a `rat` count is
  "unsupported operand types".)

### 5.4 Comparisons

- `==` and `!=` never fail. Two numbers are equal when their values are
  equal. Two strings are equal when they have the same characters. Two
  lists are equal when they have the same length and their elements are
  pairwise equal. `true`, `false`, `nil` are each equal only to
  themselves. Functions are equal only to themselves (identity). Values of
  different types are never equal (`int` and `rat` count as the same type
  here, though by normalization they are never equal to each other).
  Comparing a list that contains itself is not specified.
- `<`, `<=`, `>`, `>=` are defined for two numbers (numeric order) and two
  strings (lexicographic order by code point). Anything else:
  `TallyTypeError` `'OP' not supported between 'T1' and 'T2'`.
- Comparisons chain as in Python: `a < b <= c` means `a < b and b <= c`
  except that `b` is evaluated at most once, and evaluation stops at the
  first comparison that is false. All six operators chain with each other:
  `1 < 2 == true` means `1 < 2 and 2 == true`, which is `false`.
- The result of a comparison chain is always a `bool`.

### 5.5 Logical operators

- `a and b`: evaluate `a`; if it is falsy the result is `a` itself and `b`
  is not evaluated; otherwise the result is `b`.
- `a or b`: evaluate `a`; if it is truthy the result is `a` itself and `b`
  is not evaluated; otherwise the result is `b`.
- `not a` is `true` if `a` is falsy, else `false`.

### 5.6 Indexing and slicing

Indexing and slicing apply to lists and strings. Indexing a string gives a
one-character string; slicing a list gives a new list, slicing a string a
string.

- An index `i` must be an `int`; a negative `i` counts from the end
  (`-1` is the last element). If `i < -len` or `i >= len`:
  `TallyIndexError` `list index out of range` or `string index out of range`.
- A slice `x[a:b]` takes elements with positions from `a` up to but not
  including `b`. Either bound may be omitted (`x[:b]`, `x[a:]`, `x[:]`);
  an omitted start means 0, an omitted end means `len`. A negative bound
  has `len` added to it; then bounds are clamped to the range `0..len`.
  If the start is not less than the end, the result is empty. Slicing
  never raises an index error.
- An index or slice bound that is not an `int`: `TallyTypeError`
  `indices must be int, not 'T'`.
- Indexing or slicing anything other than a list or string:
  `TallyTypeError` `'T' is not indexable`.
- The object's type is checked first, then the index (or the start bound,
  then the end bound), then the range.

## 6. Statements

A program is a sequence of statements. Simple statements end with `;`.
Block statements (`if`, `while`, function declarations) do not.

```
let NAME = EXPR;          let NAME;            (declares NAME as nil)
NAME = EXPR;              EXPR[EXPR] = EXPR;
EXPR;
if EXPR { ... } elif EXPR { ... } else { ... }    (elif/else optional; any number of elif)
while EXPR { ... }
break;     continue;     return EXPR;     return;
fn NAME(PARAMS) { ... }
```

Braces are always required, and `else` must be followed directly by `{`
(there is no `else if`; use `elif`). A block `{ ... }` may be empty.

### 6.1 Scopes and variables

- There is a built-in scope holding the built-in functions, a global scope
  inside it, and a new scope for each *execution* of a block: each pass
  through an `if` branch, each iteration of a `while` body, and each call
  of a function. A function call's scope holds its parameters, and the
  function body's statements run directly in that scope.
- `let NAME ...` declares NAME in the current scope. Declaring a name that
  is already declared in the *same* scope is a `TallyNameError`
  `name 'NAME' is already declared in this scope`. Declaring a name that
  exists in an outer scope (including the built-in scope) shadows it. A
  `fn NAME(...)` declaration declares NAME in the same way.
- The initializer of `let` is evaluated before NAME is declared, so
  `let x = x + 1;` in an inner scope reads the outer `x`.
- Reading NAME finds the innermost enclosing scope that declares it at
  that moment; if none does: `TallyNameError` `undefined variable 'NAME'`.
- `NAME = EXPR;` evaluates EXPR, then rebinds NAME in the innermost scope
  that declares it. If no scope declares it: `TallyNameError` `undefined
  variable 'NAME'`. If only the built-in scope declares it:
  `TallyNameError` `cannot assign to builtin 'NAME'`.
- `X[I] = V;` evaluates X, then I, then V, and only then checks them. X
  must be a list
  (for a `str`: `TallyTypeError` `'str' does not support item assignment`;
  for any other type T, `'T' does not support item assignment`). I follows
  the indexing rules of 5.6, except that the out-of-range message is
  `list assignment index out of range`. X's type is checked first, then
  I's type, then the range.
- An assignment target must be a name or an index expression (possibly
  in parentheses); a slice is not an index expression. Anything else before
  `=` is a syntax error `invalid assignment target`, reported at the `=`.

### 6.2 Control flow

- `if` evaluates conditions in order and executes the first block whose
  condition is truthy, or the `else` block if none is.
- `while` evaluates the condition before each iteration and stops when it
  is falsy.
- `break` leaves the innermost enclosing loop; `continue` skips to its
  next condition check.
- `break` or `continue` that is not inside a loop *in the same function
  body* is a syntax error `'break' outside loop` / `'continue' outside
  loop`. `return` outside any function body is a syntax error `'return'
  outside function`. These are reported at the keyword.

## 7. Functions

- `fn NAME(a, b) { ... }` (statement) creates a function and declares
  NAME bound to it in the current scope. A statement that begins with
  `fn` followed by `(` is an expression statement instead.
- `fn (a, b) { ... }` (expression) creates an anonymous function.
- Parameter lists may be empty. A repeated parameter name is a syntax
  error `duplicate parameter 'NAME'`, reported at the repeated name.
- Functions are closures: they capture the scope in which they were
  created *by reference*. Names are resolved when they are evaluated, not
  when the function is created, so a function can use variables (and
  call functions) declared after it in an enclosing scope, as long as they
  exist by the time the read happens; and assignments to captured
  variables are seen by everyone sharing that scope.
- A call evaluates the callee, then the arguments, then checks that the
  callee is a function, then checks the argument count, then creates a new
  scope inside the captured scope, binds the parameters, and runs the body. `return EXPR;` ends the call with that
  value; `return;` or reaching the end of the body gives `nil`.
- Calling a value that is not a function: `TallyTypeError` `'T' is not
  callable`.
- Wrong number of arguments: `TallyTypeError` `F expected N arguments, got
  M`, where F is the function's display form (section 4), N the
  parameter count and M the argument count. The word is always
  `arguments`, even for 1.
- Recursion limit: at most 200 calls of user-defined functions may be
  active at the same time. A call that would make 201 active raises
  `TallyRecursionError` `maximum recursion depth exceeded`. Calls of
  built-in functions do not count. A recursion of depth 200 must work,
  however much the function's body nests blocks and expressions.

### 7.1 Built-in functions

| function | behaviour |
|---|---|
| `print(v...)` | any number of arguments; writes their display forms separated by single spaces, then `\n`. Returns `nil`. |
| `len(x)` | number of elements of a list or characters of a string; otherwise `TallyTypeError` `len() argument must be str or list, not 'T'` |
| `str(v)` | the display form of `v` as a string |
| `type(v)` | the type name of `v` as a string |
| `push(xs, v)` | appends `v` to the list `xs` in place, returns `nil`; if `xs` is not a list, `TallyTypeError` `push() argument 1 must be list, not 'T'` |
| `range(n)`, `range(a, b)` | the list of ints `0..n-1`, or `a..b-1` (empty if `n <= 0` or `a >= b`); an argument that is not an `int`: `TallyTypeError` `range() arguments must be int, not 'T'` |

Built-ins with a fixed argument count use the arity message of section 7
(e.g. `<builtin len> expected 1 arguments, got 2`). For `range` the
message is `<builtin range> expected 1 or 2 arguments, got M`. The
argument count is checked before the argument types.

## 8. Grammar summary

```
program    := stmt* EOF
stmt       := "let" IDENT ("=" expr)? ";"
            | "fn" IDENT "(" params? ")" block
            | "if" expr block ("elif" expr block)* ("else" block)?
            | "while" expr block
            | "break" ";" | "continue" ";" | "return" expr? ";"
            | expr ("=" expr)? ";"
block      := "{" stmt* "}"
params     := IDENT ("," IDENT)*
expr       := or
or         := and ("or" and)*
and        := not ("and" not)*
not        := "not" not | cmp
cmp        := sum (CMPOP sum)*
sum        := term (("+" | "-") term)*
term       := unary (("*" | "/" | "//" | "%") unary)*
unary      := "-" unary | power
power      := postfix ("**" unary)?
postfix    := primary ( "(" args? ")" | "[" expr "]" | "[" expr? ":" expr? "]" )*
args       := expr ("," expr)*
primary    := NUMBER | STRING | "true" | "false" | "nil" | IDENT
            | "(" expr ")" | "[" (expr ("," expr)* ","?)? "]"
            | "fn" "(" params? ")" block
```

## 9. Errors

All exceptions derive from `TallyError` and carry `message` (the message
text defined in this spec), `line`, and `output` (section 1). Their
`__str__` is defined in `tally/errors.py`.

### 9.1 Syntax errors

`TallySyntaxError` additionally carries `column`. Exactly one syntax
error is reported per program: reading tokens from the start of the
source, the first token that is *bad* determines it. A token is bad if
it cannot be lexed (section 2; the error is the lexical one, at the
position section 2 gives, even if the token would also have been
unexpected), or if the text up to and including it cannot be the
beginning of a valid program, or if it is the token at which one of the
checks of sections 6.1, 6.2 and 7 (`invalid assignment target`,
`'break' outside loop`, `duplicate parameter`, and so on) fails. Text
after the bad token is never examined, so it does not matter whether it
contains further errors.

Parse errors other than those named elsewhere have the message
`unexpected token 'TEXT'`, where TEXT is the offending token exactly as
written in the source (for a string token, including its quotes), reported
at the start of that token; or `unexpected end of input`, reported at the
position just past the last character of the source (if the source ends
with a newline, that is column 1 of the following line; an empty source
has nothing to report).

### 9.2 Runtime errors

`TallyNameError`, `TallyTypeError`, `TallyZeroDivisionError`,
`TallyIndexError`, `TallyRecursionError`. The `line` of a runtime error is
the line of the token responsible for it:

- undefined or builtin-assignment names, and `let`/`fn` redeclarations:
  the name token;
- binary and unary operator errors (type errors, division by zero, bad
  exponents): the operator token; for a failing comparison, the operator
  of that comparison;
- everything that happens in a call (not callable, wrong argument count,
  recursion limit, and any error raised by a built-in function): the
  call's `(` token;
- indexing, slicing and item-assignment errors: the `[` token.

An error raised inside a function body keeps the line where it happened;
it does not take the line of the call.
