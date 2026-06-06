const listeners = new Set();
let selectedChannel = "Cz";
let availableChannels = [];

export function configureChannels(channels) {
  availableChannels = channels.slice();
  if (!availableChannels.includes(selectedChannel)) {
    selectedChannel = availableChannels[0] || "Cz";
  }
}

export function getChannel() {
  return selectedChannel;
}

export function getChannelIndex() {
  return Math.max(0, availableChannels.indexOf(selectedChannel));
}

export function setChannel(name) {
  if (!availableChannels.includes(name) || name === selectedChannel) return;
  selectedChannel = name;
  listeners.forEach((fn) => fn(name));
}

export function onChannelChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

