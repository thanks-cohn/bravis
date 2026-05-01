# bra-vis

## Branch Visibility for RTS

bra-vis is the visual interpreter for the Relative Taxonomy Shorthand (RTS) language used in xmeta.

It takes an RTS expression and renders the resulting structure as a readable tree.

---

## What It Is

bra-vis does not store structure.

It reveals it.

Given a shorthand expression, it reconstructs hierarchy from movement, context, and known structure.

---

## Relationship to RTS

RTS defines how structure is written.

bra-vis defines how structure is understood.

RTS is the language.  
bra-vis is the reader.

---

## Usage

Run:

python bravis.py "<RTS expression>"

Example:

python bravis.py "mammalia:primates,carnivora|||plantae"

Output:

unknown
└── unknown
    └── unknown
        ├── mammalia
        │   ├── primates
        │   └── carnivora
        └── plantae

---

## What It Does

- parses RTS expressions  
- applies movement (ascend / descend / sibling)  
- builds structure incrementally  
- renders a tree  
- exposes missing hierarchy as unknown  

---

## Chained Movement

RTS allows chained movement such as:

|||::

This means:

ascend three levels  
then descend two levels  

A node can be inserted after this movement.

---

## Why This Matters

RTS expressions often omit intermediate structure.

bra-vis makes them legible.

It resolves missing levels using:

1. indexed structure  
2. local context  
3. unknown placeholders  

Because of this, expressions like:

|||::

remain valid and meaningful.

---

## Index

bra-vis maintains an internal index of known nodes.

This allows it to:

- reuse existing structure  
- infer intermediate levels when safe  
- avoid rewriting full hierarchies  

If inference is not safe, it defaults to unknown.

---

## Example

python bravis.py "life:animalia:chordata:mammalia:carnivora|||:::cetacea"

Output:

life
└── animalia
    └── chordata
        └── mammalia
            ├── carnivora
            └── cetacea

---

## Design Principle

bra-vis does not guess.

It either knows, infers safely, or shows unknown.

---

## Role

xmeta writes structure  
bra-vis reads structure  

Together they allow:

- fast annotation  
- flexible hierarchy  
- navigation without full paths  

