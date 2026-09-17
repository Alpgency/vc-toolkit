# Alpgency VC Toolkit

Two systems we built for venture funds, published with fictional data so you
can read how they work and run them yourself.

## network-graph/

Answers "who on our team can open a door into company X".

It infers who your partners likely know from overlapping employment (same
company, overlapping dates) and adds their current board and advisory seats
as confirmed doors. The result is a scored graph you can browse, plus a chat
box that answers questions through deterministic graph tools and cites every
name it returns.

See [network-graph/README.md](network-graph/README.md).

## dealflow-agent/

Turns a forwarded message into a researched, scored deal in your CRM.

A partner forwards one company, or a message listing many, to a chat bot. The
agent researches the founders and the company on the live web, checks the
forward's claims, scores the deal against your thesis (weights computed in
code, not by the model), and writes it to a self-hosted Twenty CRM. Outreach
only starts after a human confirms it.

See [dealflow-agent/README.md](dealflow-agent/README.md).

## Data

Every fund, person, and company in this repository is fictional. Domains end
in `.example`.

## License

Internal use only. See [LICENSE](LICENSE).

Built by [Alpgency](https://alpgency.xyz).
