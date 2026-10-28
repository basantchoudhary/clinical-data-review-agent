# Clinical data review agent

An agent that reviews one patient's clinical-trial record across forms and visits,
finds inconsistencies that field-level edit checks miss, and drafts queries for a
data manager to approve. It never changes trial data and never sends anything itself.

- **Real system:** OpenClinica Community Edition 3.x (open-source EDC, CDISC ODM).
- **Data:** the public CDISC pilot study (xanomeline), from the PHUSE GitHub repository.
- **Platform:** a Databricks Free Edition lakehouse with SDTM-aligned layers; Claude for the agent.
- **Shape:** rules first (edit checks in the pipeline), the agent only where rules cannot reach, a person approves every query.

Agent Master List id: **AG-102**.

## Start here

0. [The plan: goals, phases, owners](docs/PLAN.html)
1. [Lesson 1: how trial data gets clean, and where an agent fits](docs/learn/01-trial-data-and-agents.html)
2. [Architecture decisions](docs/DECISIONS.md): D1–D3 decided, D4–D8 open
3. Lesson 3: the frameworks that check the architecture (AHC, AAC, AgentTwin)

## Get the data

The raw SDTM files are not committed. Download them:

```bash
mkdir -p data/raw/sdtm && cd data/raw/sdtm
for f in dm ae cm lb vs ds sv ex mh suppae relrec ta tv; do
  curl -sfLO "https://raw.githubusercontent.com/phuse-org/phuse-scripts/master/data/sdtm/cdiscpilot01/$f.xpt"
done
```
