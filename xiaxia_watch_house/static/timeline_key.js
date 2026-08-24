(function exposeTimelineKey(root, factory) {
  const entryKey = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = entryKey;
  if (root) root.XiaxiaTimelineEntryKey = entryKey;
})(typeof globalThis !== 'undefined' ? globalThis : this, function buildTimelineKey() {
  return function timelineEntryKey(entry) {
    if (!entry || !entry.content_type) return null;
    if (entry.content_type === 'user_annotation' && entry.annotation_id) {
      return `annotation:${entry.annotation_id}`;
    }
    if (entry.content_type === 'xiaxia_thought' && entry.thought_id) {
      return `thought:${entry.thought_id}`;
    }
    if (entry.content_type === 'xiaxia_reply' && entry.reply_id) {
      return `reply:${entry.reply_id}`;
    }
    return null;
  };
});
