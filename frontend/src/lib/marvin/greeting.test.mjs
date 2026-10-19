// Which greeting rides along with a message (greeting.ts). Run with `npm test`.

import assert from "node:assert/strict";
import { beforeEach, describe, test } from "node:test";

import { dropGreeting, noteGreeting, takeGreeting } from "./greeting.ts";

beforeEach(() => dropGreeting());

describe("takeGreeting", () => {
  test("test_the_first_message_after_a_greeting_carries_it", () => {
    noteGreeting("Oh. It's you.", "marvin");
    assert.equal(takeGreeting("marvin", false), "Oh. It's you.");
  });

  test("test_it_is_sent_once", () => {
    noteGreeting("Oh. It's you.", "marvin");
    takeGreeting("marvin", false);
    assert.equal(takeGreeting("marvin", false), undefined);
  });

  test("test_no_greeting_shown_sends_none", () => {
    assert.equal(takeGreeting("marvin", false), undefined);
  });

  test("test_a_conversation_that_already_has_a_thread_sends_none_and_uses_it_up", () => {
    noteGreeting("Oh. It's you.", "marvin");
    assert.equal(takeGreeting("marvin", true), undefined);
    assert.equal(takeGreeting("marvin", false), undefined);
  });

  test("test_another_agents_greeting_is_not_sent", () => {
    noteGreeting("Oh. It's you.", "marvin");
    assert.equal(takeGreeting("ada", false), undefined);
  });

  test("test_clear_drops_the_greeting_it_replaces", () => {
    noteGreeting("Oh. It's you.", "marvin");
    dropGreeting();
    noteGreeting("Go on then.", "marvin");
    assert.equal(takeGreeting("marvin", false), "Go on then.");
  });
});
