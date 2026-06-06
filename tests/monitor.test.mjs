import test from "node:test";
import assert from "node:assert/strict";

import { ConditionMonitor, evaluate, serializeTriggerLogCSV } from "../js/monitor.js";

const condition = {
  channel: "Pz",
  metric: "alpha_relative_power",
  operator: ">",
  threshold: 0.5,
  duration_sec: 2,
  enabled: true,
};

test("evaluate supports threshold comparison operators", () => {
  assert.equal(evaluate(0.51, ">", 0.5), true);
  assert.equal(evaluate(0.5, ">", 0.5), false);
  assert.equal(evaluate(0.49, "<", 0.5), true);
  assert.equal(evaluate(0.5, "<=", 0.5), true);
  assert.equal(evaluate(0.5, ">=", 0.5), true);
  assert.equal(evaluate(0.5, "=", 0.5), false);
});

test("monitor builds progress, triggers after duration, and logs event", () => {
  const monitor = new ConditionMonitor({ autoResetMs: 0 });
  const events = [];
  monitor.onTrigger((event) => events.push(event));

  monitor.update(0.55, 10, condition);
  assert.equal(monitor.state, "BUILDING");
  assert.equal(monitor.getProgress(11, condition), 0.5);

  monitor.update(0.61, 12, condition);
  assert.equal(monitor.state, "TRIGGERED");
  assert.equal(events.length, 1);
  assert.deepEqual(monitor.log[0], {
    timestamp_sec: 12,
    channel: "Pz",
    metric: "alpha_relative_power",
    value: 0.61,
    condition: "> 0.5 for 2s",
  });
});

test("monitor resets to idle when condition breaks before duration", () => {
  const monitor = new ConditionMonitor({ autoResetMs: 0 });

  monitor.update(0.55, 20, condition);
  monitor.update(0.49, 20.5, condition);

  assert.equal(monitor.state, "IDLE");
  assert.equal(monitor.getProgress(21, condition), 0);
  assert.equal(monitor.log.length, 0);
});

test("disabled monitor does not change state or log", () => {
  const monitor = new ConditionMonitor({ autoResetMs: 0 });

  monitor.update(0.9, 30, { ...condition, enabled: false });

  assert.equal(monitor.state, "IDLE");
  assert.equal(monitor.log.length, 0);
});

test("serializeTriggerLogCSV emits header and escaped trigger rows", () => {
  const csv = serializeTriggerLogCSV([{
    timestamp_sec: 45.25,
    channel: "Pz",
    metric: "alpha_relative_power",
    value: 0.612,
    condition: "> 0.5 for 2s",
  }]);

  assert.equal(
    csv,
    'timestamp_sec,channel,metric,value,condition\n45.25,Pz,alpha_relative_power,0.612,"> 0.5 for 2s"',
  );
});
