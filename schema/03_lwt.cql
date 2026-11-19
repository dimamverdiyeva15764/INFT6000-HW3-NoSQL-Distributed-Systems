-- Experiment 6 (Paxos lightweight transactions). Owner: Habib Hasanov.
-- One partition per handle: an LWT runs one Paxos instance per partition among that
-- partition's replicas (all three nodes, RF = 3), so every handle is an independent
-- consensus instance. Applied by `make schema` after 01/02 (file-name order).
CREATE TABLE IF NOT EXISTS chat.usernames (
  handle text PRIMARY KEY,
  owner  text
);
