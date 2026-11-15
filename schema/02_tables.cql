CREATE TABLE IF NOT EXISTS chat.messages (
  room       text,
  msg_id     timeuuid,
  author     text,
  body       text,
  writer_run text,
  PRIMARY KEY (room, msg_id)
) WITH CLUSTERING ORDER BY (msg_id DESC);

CREATE TABLE IF NOT EXISTS chat.room_state (
  room       text PRIMARY KEY,
  last_seq   bigint,
  updated_by text
);
