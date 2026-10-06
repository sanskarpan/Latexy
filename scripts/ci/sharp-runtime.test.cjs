'use strict'

const assert = require('node:assert/strict')
const path = require('node:path')
const test = require('node:test')

const repoRoot = path.resolve(__dirname, '..', '..')
const frontendRoot = path.join(repoRoot, 'frontend')

function findPackageRoot(entry, packageName) {
  const marker = `${path.sep}node_modules${path.sep}${packageName}${path.sep}`
  const markerIndex = entry.lastIndexOf(marker)
  assert.notEqual(markerIndex, -1, `could not locate ${packageName} package root`)
  return entry.slice(0, markerIndex + marker.length - 1)
}

const nextEntry = require.resolve('next', { paths: [frontendRoot] })
const nextRoot = findPackageRoot(nextEntry, 'next')
const optimizer = require(path.join(nextRoot, 'dist', 'server', 'image-optimizer.js'))
const sharpEntry = require.resolve('sharp', { paths: [nextRoot] })
const sharp = optimizer.getSharp(1)

function versionParts(version) {
  assert.match(String(version), /^\d+\.\d+\.\d+$/, 'expected a stable release version')
  return String(version).split('.').map(Number)
}

function assertVersionAtLeast(actual, minimum, label) {
  const actualParts = versionParts(actual)
  const minimumParts = versionParts(minimum)
  for (let index = 0; index < minimumParts.length; index += 1) {
    const actualPart = actualParts[index] ?? 0
    if (actualPart !== minimumParts[index]) {
      assert.ok(actualPart > minimumParts[index], `${label} ${actual} is below ${minimum}`)
      return
    }
  }
}

test('resolves the active Next sharp binary at the patched versions', () => {
  assert.match(nextEntry, /node_modules[\\/]next[\\/]dist[\\/]server[\\/]next\.js$/)
  assert.match(sharpEntry, /node_modules[\\/]sharp[\\/]dist[\\/]index\.cjs$/)
  assertVersionAtLeast(sharp.versions.sharp, '0.35.5', 'sharp')
  assertVersionAtLeast(sharp.versions.rsvg, '2.63.2', 'librsvg')
})

test('initializes the same Next image optimizer sharp instance', () => {
  assert.equal(sharp, require(sharpEntry))
  assert.equal(typeof optimizer.getSharp, 'function')
  assert.equal(typeof optimizer.optimizeImage, 'function')
  assert.equal(typeof sharp.block, 'function')
  assert.equal(typeof sharp.unblock, 'function')
  assert.equal(typeof sharp.concurrency, 'function')
})

test('resizes a benign raster through the active optimizer binary', async () => {
  const input = await sharp({
    create: {
      width: 2,
      height: 2,
      channels: 4,
      background: { r: 255, g: 0, b: 0, alpha: 1 },
    },
  }).png().toBuffer()
  const output = await sharp(input).resize(1, 1).png().toBuffer()
  const metadata = await sharp(output).metadata()

  assert.equal(metadata.format, 'png')
  assert.equal(metadata.width, 1)
  assert.equal(metadata.height, 1)
})

test('converts a benign SVG through the active optimizer binary', async () => {
  const input = Buffer.from(
    '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2">' +
      '<rect width="2" height="2" fill="#00ff00"/></svg>',
  )
  const output = await sharp(input).png().toBuffer()
  const metadata = await sharp(output).metadata()

  assert.equal(metadata.format, 'png')
  assert.equal(metadata.width, 2)
  assert.equal(metadata.height, 2)
})
