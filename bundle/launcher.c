#include <Python.h>
#include <mach-o/dyld.h>
#include <libgen.h>
#include <stdio.h>
#include <string.h>
/* Lavalier.app/Contents/MacOS/Lavalier: embeds the framework Python so macOS attributes
   the Bluetooth grant to this bundle, then runs `lavalier.app` (or the module in argv[1]
   when it starts with "-m"). Search paths come from Contents/Resources/paths.txt. */
int main(int argc, char **argv) {
    char exe[4096]; uint32_t n = sizeof exe;
    if (_NSGetExecutablePath(exe, &n) != 0) return 70;
    char res[4200]; snprintf(res, sizeof res, "%s/../Resources/paths.txt", dirname(exe));
    PyConfig cfg; PyConfig_InitIsolatedConfig(&cfg);
    cfg.module_search_paths_set = 1; cfg.parse_argv = 0;
    PyStatus st = PyConfig_SetBytesString(&cfg, &cfg.home, PY_HOME);     /* -DPY_HOME="<framework>" at build */
    if (PyStatus_Exception(st)) goto fail;
    FILE *f = fopen(res, "r"); char line[4096];
    if (!f) return 71;
    while (fgets(line, sizeof line, f)) { line[strcspn(line, "\n")] = 0; if (*line) PyWideStringList_Append(&cfg.module_search_paths, Py_DecodeLocale(line, NULL)); }
    fclose(f);
    PyWideStringList_Append(&cfg.module_search_paths, Py_DecodeLocale(PY_STDLIB, NULL));          /* -DPY_STDLIB */
    PyWideStringList_Append(&cfg.module_search_paths, Py_DecodeLocale(PY_STDLIB "/lib-dynload", NULL));
    const char *module = (argc > 2 && strcmp(argv[1], "-m") == 0) ? argv[2] : "lavalier.app";
    int first = (argc > 2 && strcmp(argv[1], "-m") == 0) ? 3 : 1;
    PyConfig_SetBytesString(&cfg, &cfg.run_module, module);
    PyStatus a = PyConfig_SetBytesArgv(&cfg, argc - first + 1, argv + first - 1);
    if (PyStatus_Exception(a)) goto fail;
    st = Py_InitializeFromConfig(&cfg); if (PyStatus_Exception(st)) goto fail;
    PyConfig_Clear(&cfg);
    return Py_RunMain();
fail:
    PyConfig_Clear(&cfg); Py_ExitStatusException(st); return 1;
}
