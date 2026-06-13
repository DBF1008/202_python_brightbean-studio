/**
 * Media Library — Alpine.js & HTMX integrations
 *
 * This file is loaded on library pages via {% static 'js/media-library.js' %}.
 * Alpine components (mediaLibrary, imageCropper, videoTrimmer, tagInput)
 * are defined inline in their respective templates so they have access
 * to Django template variables. This file contains shared utilities.
 */

(function () {
  'use strict';

  // ── HTMX event: refresh grid after uploads complete ──
  document.body.addEventListener('uploadsComplete', function () {
    var grid = document.getElementById('asset-grid');
    if (grid) {
      // Trigger a page reload of the grid via HTMX
      var url = grid.getAttribute('data-refresh-url');
      if (url) {
        htmx.ajax('GET', url, { target: '#asset-grid', swap: 'innerHTML' });
      } else {
        // Fallback: reload the page
        window.location.reload();
      }
    }
  });

  // ── HTMX event: close detail panel after asset deletion ──
  document.body.addEventListener('assetDeleted', function () {
    // If Alpine is available, close the detail panel
    var lib = document.querySelector('[x-data*="mediaLibrary"]');
    if (lib && lib.__x) {
      lib.__x.$data.detailOpen = false;
    }
    // Refresh the grid
    var grid = document.getElementById('asset-grid');
    if (grid) {
      window.location.reload();
    }
  });

  // ── Keyboard shortcut: Cmd/Ctrl+U to trigger upload ──
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'u') {
      var fileInput = document.querySelector('[x-ref="fileInput"]');
      if (fileInput) {
        e.preventDefault();
        fileInput.click();
      }
    }
  });

  // ── Format file size for display ──
  window.formatFileSize = function (bytes) {
    if (bytes === 0) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + units[i];
  };

  // ── Format duration for display ──
  window.formatDuration = function (seconds) {
    var mins = Math.floor(seconds / 60);
    var secs = Math.floor(seconds % 60);
    return mins + ':' + (secs < 10 ? '0' : '') + secs;
  };

})();
