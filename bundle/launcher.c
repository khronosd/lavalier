#include <Python.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <stdio.h>
#include <string.h>
/* Lavalier.app/Contents/MacOS/Lavalier: embeds the framework Python so macOS attributes
   the Bluetooth grant to this bundle, then runs `lavalier.app` (or the module in argv[2]
   when argv[1] is "-m"). Search paths come from Contents/Resources/paths.txt. */

/* Append a locale-decoded string to a search path list; 0 on success. */
static int append_path(PyConfig *cfg, const char *s) {
    wchar_t *w = Py_DecodeLocale(s, NULL);
    if (!w) return -1;
    PyStatus r = PyWideStringList_Append(&cfg->module_search_paths, w);
    PyMem_RawFree(w);
    return PyStatus_Exception(r) ? -1 : 0;
}

int main(int argc, char **argv) {
    char exe[4096]; uint32_t n = sizeof exe;
    if (_NSGetExecutablePath(exe, &n) != 0) return 70;
    char res[4200]; snprintf(res, sizeof res, "%s/../Resources/paths.txt", dirname(exe));
    /* launchd gives the process no locale; without UTF-8 mode the isolated config would read and
       write text files as ASCII (the day file's star once failed to write). */
    PyPreConfig pre; PyPreConfig_InitIsolatedConfig(&pre);
    pre.utf8_mode = 1;
    PyStatus pst = Py_PreInitialize(&pre);
    if (PyStatus_Exception(pst)) Py_ExitStatusException(pst);
    PyConfig cfg; PyConfig_InitIsolatedConfig(&cfg);
    cfg.module_search_paths_set = 1; cfg.parse_argv = 0;
    cfg.install_signal_handlers = 1;  /* KeyboardInterrupt and a clean SIGTERM for the long-running app */
    cfg.site_import = 0;              /* paths.txt lists everything; never pull in the global site-packages */
    PyStatus st = PyConfig_SetBytesString(&cfg, &cfg.home, PY_HOME);     /* -DPY_HOME="<framework>" at build */
    if (PyStatus_Exception(st)) goto fail;
    FILE *f = fopen(res, "r"); char line[4096];
    if (!f) { fprintf(stderr, "Lavalier: cannot read %s\n", res); PyConfig_Clear(&cfg); return 71; }
    while (fgets(line, sizeof line, f)) {
        line[strcspn(line, "\n")] = 0;
        if (*line && append_path(&cfg, line) != 0) { fclose(f); goto oom; }
    }
    fclose(f);
    if (append_path(&cfg, PY_STDLIB) != 0) goto oom;                       /* -DPY_STDLIB */
    if (append_path(&cfg, PY_STDLIB "/lib-dynload") != 0) goto oom;
    const char *module = (argc > 2 && strcmp(argv[1], "-m") == 0) ? argv[2] : "lavalier.app";
    int first = (argc > 2 && strcmp(argv[1], "-m") == 0) ? 3 : 1;
    st = PyConfig_SetBytesString(&cfg, &cfg.run_module, module);
    if (PyStatus_Exception(st)) goto fail;
    st = PyConfig_SetBytesArgv(&cfg, argc - first + 1, argv + first - 1);
    if (PyStatus_Exception(st)) goto fail;
    st = Py_InitializeFromConfig(&cfg); if (PyStatus_Exception(st)) goto fail;
    PyConfig_Clear(&cfg);
    return Py_RunMain();
oom:
    fprintf(stderr, "Lavalier: cannot build the module search path\n");
    PyConfig_Clear(&cfg); return 72;
fail:
    PyConfig_Clear(&cfg); Py_ExitStatusException(st); return 1;
}
