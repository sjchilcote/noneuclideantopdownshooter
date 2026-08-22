# Litc clear technical prose

This writing system uses the parts of Simplified Technical English that expose ambiguity and discards the parts designed principally for machine translation. Its purpose is to make logic visible to authors, readers, and implementation agents.

## Meaning comes first

Every sentence must communicate a definite claim about the product. Prefer ordinary, idiomatic English when it expresses that claim accurately. Do not replace a natural phrase with an awkward controlled-language paraphrase.

Each important noun must have a stable referent in context. Each verb must describe the actual relationship, state change, computation, or observable action. Pronouns and abstract placeholders must have unambiguous antecedents. State intermediate causal steps when omitting them would conceal how a result follows.

Do not use a familiar word with a private meaning. Do not use metaphor as a substitute for a system concept. Phrases such as “the marrow accesses the shelf body” are invalid unless those words name literal product concepts with clear, established meanings. A phrase that evokes a vague mechanism but does not specify one is a logic error, not a style defect.

## Write to communicate

Use direct sentences with explicit subjects and verbs. Keep sentences and paragraphs short enough that their logic remains visible, but prefer a longer natural sentence to several malformed or telegraphic fragments. Use articles, conjunctions, relative clauses, passive voice, and `-ing` forms when they make the meaning clearer.

Do not write to sound intelligent, comprehensive, formal, or technical. Remove throat-clearing, empty intensifiers, redundant summaries, ceremonial transitions, and claims that merely restate a heading. Technical detail belongs in the text only when it changes the reader's model of behavior.

Do not optimize prose for a grader or checker. A suggested replacement is evidence about a possible problem, not text to splice into a sentence. Rewrite the complete thought when a change is necessary.

## Terminology

Use one term consistently for one product concept. Prefer the established term from the relevant technical field. A project-specific term is valid when it names an exact code-facing object or an owner-approved product concept and its definition states that referent plainly.

The glossary records terms a reader must learn. It does not grant permission to use ordinary English, and it must not contain ordinary-word padding, invented synonyms, decorative phrases, circular definitions, or nonstandard meanings created to satisfy a checker.

## Specification evidence

An Implementation claim must trace to code or observed behavior. The prose must distinguish verified behavior, inferred intent, defects, and open decisions. A reader must be able to paraphrase the described control flow and causal relationships without inventing missing logic.

Reviewers judge meaning in context. Deterministic checks can identify structural risks, but a finding blocks acceptance only when it identifies an actual violation of this standard.
