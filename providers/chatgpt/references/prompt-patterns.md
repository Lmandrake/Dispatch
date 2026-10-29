# Framing a consultation so the answer is worth reading

The single biggest determinant of a useful reply is the framing, not the model. A request that
presents finished work gets told the work looks good; a request that points at its own weakest joint
gets a counterexample you can turn into a test.

These patterns are derived from consultations that produced real findings, and from ones that did not.

## The review request

Section order that has worked. The first and last sections do most of the work.

```markdown
Adversarial code review request — <component>, <nth> round.

<One paragraph: what the previous round found, if any. This establishes that you act on
 the advice, which measurably changes how hard the next reply tries.>

Please be harsher than feels polite. I am not asking whether the results are encouraging;
I am asking where they are still self-serving.

## 1. <What you changed, with the actual code or diff>

<The measurement. Numbers, not adjectives.>

**The rule I am least sure of.** <Name it. Say why you chose it, and what you rejected.>

Questions: <specific, answerable>

## 2. <The thing you most suspect is wrong>

**This is the part I want you to attack.** <Show it. State the convenient conclusion you
 reached and note that you are the party being graded.>

## N. The question I most want answered

<Usually: what failure classes are invisible to all my current instruments?>

Constraints: this project treats your reply as guidance, never as a grading key or a
substitute for the user's ruling. Concrete counterexamples I can turn into tests are
worth far more than an assessment of quality.
```

### Why each part earns its place

**"Be harsher than feels polite"** — without it, replies default to encouraging. It is a small thing
that visibly changes the register of the answer.

**Naming your own weakest rule** — a reviewer who has to *find* the weak joint spends its effort
locating it. A reviewer told where it is spends its effort attacking it. You lose nothing by being
honest about which rule you fitted to one example, because that is the rule that will break.

**Flagging where you are the graded party** — the strongest single move available. A consultation that
said "I classified these mismatches as the source's fault rather than my extractor's loss; that is a
convenient conclusion reached by the party being graded, interrogate it" got back a precise
verdict with a concrete fix. Asking "does this look right" would
not have.

**Asking for counterexamples over assessment** — states the deliverable. "What shape defeats this
rule" produces a test case. "Is this good" produces an adjective.

**The invisible-failure-classes question** — ask it whenever you have more than one instrument
reporting green. It is the question you cannot answer from inside, and it is where the highest-value
answers have come from.

## Design-document hardening

Same skeleton, different emphasis. Include the constraints the design must satisfy and the
alternatives you rejected **with your reasons** — otherwise the reply re-proposes them and you have
bought your own analysis a second time. Then ask specifically:

- Which assumption here, if wrong, invalidates the most downstream work?
- What does this design make expensive to change later?
- Where am I solving a problem I have not shown exists?

That last one catches speculative machinery before it is built, which is the cheapest moment.

## Stuck bug / impossibility check

Lead with what you have **ruled out and how**, because the failure mode of this request is getting
back the three things you already tried. Then:

```markdown
I have failed three times. My current model of the problem is: <state it explicitly>.
I think the most likely wrong assumption in that model is: <name it>.

What I tried, and how each failed:
1. <hypothesis> -> <observed result, not "didn't work">
2. ...
3. ...

Is there a framing in which this is straightforward that I am not seeing?
```

**State your model of the problem explicitly.** After three failures the bug is usually not where you
are looking, and the reply's job is to attack the model rather than the attempts. Writing the model
down is also frequently where you notice the flaw yourself, before sending.

For an impossibility claim, ask directly: *"I am about to tell the user this cannot be done. Before I
do — is that true, and if it is, what is the nearest thing that can be done?"* The fallback is often
more valuable than the verdict.

## When to withhold rather than inform

For a **review**, give your claims and conclusions — that is the point, you want them attacked.

For an **independent judgment** — labelling data, answering a question you also answered, grading
anything — withhold yours. A model shown your conclusion tends to ratify it, and what comes back is an
agreement check dressed as an independent measurement.

**Withhold the citation too, if the material is public.** Measured on ExampleProject: shown a document id
and section number but not the text, a model asserted the withheld text and quoted it verbatim from
training data. Naming where to look does not withhold evidence. Strip the identifiers when the point is
to measure what the supplied text contributed.

## Length

Long prompts are fine — 7,000 characters produced one of the best replies. What is not fine is
unexplained context: a reader who has to reconstruct your situation spends the reply doing that. State
the background compactly and completely, then ask precisely.
