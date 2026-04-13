# Frontend Design System

## How To Use This Document

This file explains the design language of the new frontend.

Use it when you want to understand:

- why the UI looks the way it does
- what visual rules we are following
- what “professional but attractive” means in this project
- how gamification is being used carefully

This is not just a CSS note.
It is the reasoning behind the visual system.

## The Core Design Goal

The product must feel:

- professional
- institution-grade
- attractive
- trustworthy
- modern
- calm

It must not feel:

- childish
- noisy
- flashy for no reason
- like a random admin panel template
- like a generic AI toy

That balance is the whole challenge.

## Role Tone Rules

One design system can still support different role moods.

That does not mean changing the whole product for each role.
It means changing emphasis while keeping the same foundation.

### Student

Student pages can use:

- slightly softer gradients
- more motivational framing
- journey and progress visuals

But they must still stay formal.

### Counsellor

Counsellor pages should feel:

- structured
- task-oriented
- operational

So they use stronger panels, queue patterns, and less decorative motion.

### Admin

Admin pages should feel:

- executive
- analytic
- high-signal

So they should use the least playful styling of all three roles.

## Visual Direction We Chose

We chose a visual direction based on:

- light-first enterprise product design
- soft premium surfaces
- strong typography
- subtle indigo + teal accents
- restrained motion

Why this fits the product:

- students need motivation, but also seriousness
- counsellors need clarity and speed
- admins need trust and control

## Typography

We intentionally did not use plain default browser typography.

We chose:

- `Manrope` for headings
- `Plus Jakarta Sans` for body text

Why:

- headings look strong and premium
- body text stays readable
- together they feel more like a real product than a quick prototype

## Color System

Main ideas:

- `slate / ink` for trust and clarity
- `indigo` for intelligence / product identity
- `teal` for healthy or improving states
- `gold / amber` for caution and attention
- `rose` for high-risk or urgent states

Important homepage rule:

- do not let the whole public page collapse into white-on-white surfaces
- the landing experience needs stronger dark/light section separation than the internal dashboards

Why:

- the public homepage creates first impression
- if everything is pale and low-contrast, the product feels unfinished even when the layout is correct
- stronger section contrast makes the system feel more premium without becoming noisy

Why this matters:

- users need to understand state quickly
- color must support meaning, not just decoration

## Surface System

The interface uses:

- soft white cards
- light blur glass panels in key areas
- subtle borders
- soft shadows

Why:

- this creates depth
- but keeps the UI formal
- and prevents the interface from feeling flat or cheap

## Motion Rules

We use motion in a restrained way.

Allowed motion:

- soft page rise-in
- small floating emphasis for the chatbot mark
- gentle panel transitions

Not allowed:

- aggressive bouncing
- flashy animations everywhere
- game-like celebration motion on admin pages

Why:

- motion should support orientation and polish
- not distract from institutional work

## Student Gamification Rule

The student side is the only place where stronger motivational design makes sense.

But even there, we use:

- progress journey language
- status chips
- timeline progression
- “next best action” emphasis

We do not use:

- cartoon badges
- childish rewards
- arcade-style points

Why:

- students should feel encouraged
- but the institution must still trust the tone of the product

## Counsellor And Admin Rule

Counsellor:

- light productivity framing is okay
- operational momentum is okay
- playful gamification is not appropriate

Admin:

- almost no gamification
- focus on executive clarity, state visibility, and controlled actions

Why:

- the same design pattern does not fit every role equally well

## Chatbot Visual Rule

The chatbot needed to feel:

- friendly
- memorable
- professional

That is why we used a small custom mark that feels slightly cute, but still geometric and formal.

The correct feeling is:

- “product mascot energy”
not
- “cartoon character”

## Responsive Rule

The system must work on:

- laptop
- desktop
- mobile phone

So the layout rules are:

- cards should stack cleanly
- side navigation should collapse on small screens
- chatbot should become a mobile-friendly panel
- charts should resize cleanly instead of overflowing

## Most Important Practical Rule

Every visual choice should answer this question:

`Does this make the product feel more trustworthy and more useful?`

If the answer is no, it should not be added just because it looks fancy.
