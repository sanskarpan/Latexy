// PDF.js bundles its own Webpack runtime. Next's eval development wrapper
// otherwise shadows its injected runtime with these module-private var names.
// Keep production output and PDF.js public exports unchanged.
// https://github.com/vercel/next.js/issues/89177
module.exports = function pdfjsWebpackDevScope(source) {
  this.cacheable?.()
  if (!source.includes('pdfjsVersion = 5.4.296') ||
      !source.includes('var __webpack_require__ = {};') ||
      !source.includes('var __webpack_exports__ = {};') ||
      source.includes('__latexy_pdfjs_')) {
    throw new Error('Review the PDF.js development scope workaround for the installed bundle')
  }
  return source.replace(/\b__webpack_(require|exports)__\b/g, '__latexy_pdfjs_$1__')
}
