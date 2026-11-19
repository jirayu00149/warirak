// Keep existing public-monitor bookmarks working after introducing the welcome page.
if(['#monitor','#reports'].includes(location.hash))location.replace('/monitor'+location.hash);
