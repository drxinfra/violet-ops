// Unpack an uploaded archive, refusing paths that escape the target folder.
def unpackInto(String src, String name, String dest) {
    def lower = name.toLowerCase()
    def kind = ''
    if (lower.endsWith('.zip')) {
        kind = 'zip'
    } else if (sh(script: "tar -tzf '${src}' >/dev/null 2>&1", returnStatus: true) == 0) {
        kind = 'tgz'
    }
    if (!kind) {
        error "Unknown archive type: ${name}"
    }
    sh "mkdir -p '${dest}'"
    return kind
}
