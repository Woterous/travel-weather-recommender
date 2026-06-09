# Product

## Register

product

## Users

This product is used by students during a course design demonstration and by teachers reviewing the system. The user context is a local Flask web app walkthrough where the data flow, scoring logic, city recommendations, and visual evidence need to be understood quickly.

## Product Purpose

The product recommends travel destinations from a fixed set of cities based on weather, air quality when available, historical stability, and user preferences. Success means the interface can clearly demonstrate the full loop from collected data to cleaned data, scoring, ranking, city detail, comparison, and historical analysis in a short classroom presentation.

## Brand Personality

Clear, evidence-driven, calm. The interface should feel like a polished analysis tool: approachable enough for a classroom audience, but precise enough that every recommendation appears traceable to visible data.

## Anti-references

Do not make it look like a generic tourism booking site, a general-purpose weather app, a marketing landing page, or a flashy data demo that hides the scoring basis. Avoid fake-looking static rankings, vague recommendation copy, overly decorative cards, and visuals that make the algorithm harder to explain.

## Design Principles

Show the recommendation evidence close to the decision.

Make the primary classroom path obvious: ranking, why, details, compare, history, preferences.

Favor dense but readable information over theatrical presentation.

Keep data freshness and degradation states visible so the local-cache strategy is understandable.

Let user preferences feel consequential by exposing how they affect scores and weights.

## Accessibility & Inclusion

Target readable contrast, keyboard-accessible controls, visible focus states, and responsive layouts for laptop projection and mobile review. Motion should be subtle and respect reduced-motion settings. Color should support meaning but never be the only way to understand score status, weather risk, or warnings.
