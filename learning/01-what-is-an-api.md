# 01 — What is an API?

**Goal:** understand the core idea of an API before touching any code.

---

## The restaurant analogy

Imagine a restaurant:
- **You (the customer)** want food but can't go into the kitchen.
- **The kitchen** has the food and knows how to make it.
- **The waiter** takes your order to the kitchen and brings food back.

The **waiter is the API**. You don't need to know how the kitchen works — you
just need to know how to *order* (the menu) and what you'll *get back* (a dish).

An **API** (Application Programming Interface) is the "waiter" between two pieces
of software: it takes **requests** and returns **responses**, following an agreed
**menu** (the contract).

## Client and server

Two roles in every API conversation:

- **Client** — the one who *asks*. (A website, a phone app, another program, or
  even you typing a command.)
- **Server** — the one who *answers*. (Our FastAPI app.)

```
   Client  ──────  "give me the scrape data for 2026-03-15"  ──────▶  Server
           ◀──────  "here it is: [ {...}, {...}, ... ]"       ──────
```

The client and server can be written in totally different languages, run on
different computers, anywhere in the world. They only need to agree on the
**contract**: what you can ask, and what comes back. That's the whole point of an
API — it's a **contract**, not a program you run.

## Why APIs exist

Without an API, every program that wanted your scrape data would need direct
access to your files, your database, your code — messy and dangerous. With an
API:
- Consumers ask in a simple, standard way (HTTP — next lesson).
- You control exactly what they can see and do.
- You can change *how* things work inside without breaking them, as long as the
  contract stays the same.

## Where our project fits

This repo **is** a server. Its API lets a client ask for daily scrape data:

> Client: "Give me the products scraped on **2026-03-15**."
> Server: *reads the stored data, sends back JSON.*

The client never sees the files, the storage, or the conversion tricks inside.
It just uses the menu. You've already seen that menu — it's the page at
**http://localhost:8000/docs**.

## "Web API" / "REST API" — same thing here

You'll hear **web API**, **HTTP API**, **REST API**. For us they all mean the
same practical thing: an API you talk to over the web using HTTP. We'll meet HTTP
next. (REST is just a popular *style* of designing these — common conventions
like "use a URL to name a thing, use GET to read it.")

## Key takeaways
- An API is a **contract** for programs to talk, request → response.
- **Client** asks; **server** answers.
- It hides the messy internals and exposes a clean, controlled "menu."
- Our project is a server whose menu is visible at `/docs`.

➡️ Next: **[02 — HTTP basics](02-http-basics.md)** — the language the request and
response are actually written in.
