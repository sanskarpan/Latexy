import { existsSync, rmSync, statSync } from 'node:fs'
import { join } from 'node:path'

const command = process.argv[2]
const frontendRoot = process.cwd()
const nextRoot = join(frontendRoot, '.next')

const requiredFiles = [
    join(nextRoot, 'BUILD_ID'),
    join(nextRoot, 'build-manifest.json'),
    join(nextRoot, 'prerender-manifest.json'),
    join(nextRoot, 'routes-manifest.json'),
    join(nextRoot, 'server', 'app-paths-manifest.json'),
]

const standaloneEntrypoints = [
    join(nextRoot, 'standalone', 'server.js'),
    join(nextRoot, 'standalone', 'frontend', 'server.js'),
]

function fail(message) {
    console.error(`Frontend build validation failed: ${message}`)
    process.exit(1)
}

function isNonEmptyFile(filePath) {
    return existsSync(filePath) && statSync(filePath).isFile() && statSync(filePath).size > 0
}

if (command === 'preflight') {
    const major = Number.parseInt(process.versions.node.split('.')[0], 10)
    if (major !== 22) {
        fail(
            `Node ${process.versions.node} is unsupported for this build. Use Node 22.x; ` +
                'odd-numbered Node releases can make Next 14 exit successfully without producing artifacts.'
        )
    }

    // A failed Next build must not be able to pass validation using output left by
    // an earlier successful build.
    for (const artifact of [...requiredFiles, join(nextRoot, 'standalone')]) {
        rmSync(artifact, { force: true, recursive: true })
    }
} else if (command === 'artifacts') {
    const missing = requiredFiles.filter(filePath => !isNonEmptyFile(filePath))
    if (!standaloneEntrypoints.some(isNonEmptyFile)) {
        missing.push(`${join(nextRoot, 'standalone')}/[frontend/]server.js`)
    }

    if (missing.length > 0) {
        fail(`Next exited without complete production output:\n- ${missing.join('\n- ')}`)
    }

    console.log('Frontend build artifacts validated.')
} else {
    fail('expected command: preflight or artifacts')
}
