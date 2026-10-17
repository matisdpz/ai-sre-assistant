-- Runs once, when the database volume is first created.
-- Integration tests use this separate database so they never touch development data.
CREATE DATABASE sre_test;
