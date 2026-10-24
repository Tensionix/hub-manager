using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Controls.Templates;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using AudionHubManager.Core;

namespace AudionHubManager;

/// <summary>
/// СИНХРОНИЗАЦИЯ: the remotes of the repository - their addresses, SSH or HTTPS, how far the current branch is from each
/// - with fetch, pull and push; a new remote put together from a platform, an owner and a name (the address is built by
/// the console command, never typed with a password in it); the access - who signs the commits, which servers let you
/// in, the token of Forgejo, which goes to the store of Git from the window's own field and nowhere else; CI.
/// </summary>
public partial class MainWindow
{
    ListBox? _remoteList;
    StackPanel? _access;
    string _platform = "github", _urlType = "ssh";
    TextBox? _remoteName, _owner, _repoName, _server, _sshPort;
    TextBlock? _builtUrl;
    StackPanel? _platformRow, _typeRow2;
    JsonObject? _authReport;

    sealed class RemoteRow
    {
        public string Name = "", Fetch = "", Push = "", Kind = "", Provider = "";
        public (int Ahead, int Behind)? Distance;
    }

    Control BuildSync()
    {
        var page = new Grid { RowDefinitions = new RowDefinitions("Auto,Auto,*") };
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Margin = new Thickness(0, 0, 0, 10) };
        head.Children.Add(new TextBlock { Classes = { "pagetitle" }, Text = Upper(Lang.T("СИНХРОНИЗАЦИЯ")) });
        var tools = new StackPanel { Orientation = Orientation.Horizontal };
        tools.Children.Add(OpCanon("remotes", "git remote -v", () => null, cls: "quiet", sm: true));
        Grid.SetColumn(tools, 2);
        head.Children.Add(tools);
        page.Children.Add(head);

        _remoteList = Rows("remotes");
        _remoteList.ItemTemplate = new FuncDataTemplate<RemoteRow>((row, _) => row is null ? new Panel() : RemoteView(row), supportsRecycling: false);
        var table = new DockPanel();
        var heads = Heads("26,110,*,64,80,Auto", "", Lang.T("REMOTE"), Lang.T("АДРЕС"), Lang.T("ВИД"), "↑ ↓", "");
        DockPanel.SetDock(heads, Dock.Top);
        table.Children.Add(heads);
        table.Children.Add(_remoteList);
        var tableBox = new Border { Classes = { "pane" }, Child = table, MaxHeight = 170, MinHeight = 90, Margin = new Thickness(0, 0, 0, 10) };
        Grid.SetRow(tableBox, 1);
        page.Children.Add(tableBox);

        var two = new Grid { ColumnDefinitions = new ColumnDefinitions("*,10,*") };
        Grid.SetRow(two, 2);
        page.Children.Add(two);
        two.Children.Add(new ScrollViewer { Content = BuildRemoteForm() });
        _access = new StackPanel { Spacing = 10 };
        var right = new ScrollViewer { Content = _access };
        Grid.SetColumn(right, 2);
        two.Children.Add(right);
        ShowAccess();

        SetOps(
            OpCanon("fetch", "fetch всё", () => null, "F2"),
            OpCanon("pull", "pull", PullValues),
            null,
            Grow(new Border()),
            Op("во все remote", PushAll, Canon.Get("push_all").Tip(), "net", id: "op_push_all", command: Canon.Get("push_all").Short),
            Op(_state is { Ahead: > 0 } s ? "PUSH ↑" + s.Ahead : "PUSH", () => RunCanon("push", PushValues()), Canon.Get("push").Tip(), "net", cls: "fill", id: "op_push", command: Canon.Get("push").Short));
        _keys[Key.F2] = () => RunCanon("fetch");
        return page;
    }

    /// <summary>The branch and its tags into every remote of the repository, one after another.</summary>
    void PushAll()
    {
        if (ActiveRoot() is not { } root || _remoteNames.Count == 0) { SetStatus("У репозитория нет remote."); return; }
        // The current branch under its own name into every remote - not the name of its pair on one of them.
        var branch = _state?.Branch is { Length: > 0 } b && !_state.Detached ? b : _project?.Branch ?? "main";
        var entry = Canon.Get("push_all");
        RunSteps(_remoteNames.Select(remote => GitStep(entry, entry.Argv(new() { ["remote"] = remote, ["branch"] = branch }), root, name: "git push → " + remote)).ToArray());
    }

    async Task UpdateSync()
    {
        if (_remoteList is null) return;
        if (ActiveRoot(true) is not { } root) { _remoteList.ItemsSource = null; return; }
        var remotes = await Git.Remotes(root);
        var branch = _state?.Branch ?? "";
        var rows = new List<RemoteRow>();
        foreach (var (name, fetch, push) in remotes)
        {
            var row = new RemoteRow { Name = name, Fetch = fetch, Push = push, Kind = fetch.StartsWith("http", StringComparison.OrdinalIgnoreCase) ? "HTTPS" : fetch.Contains("://") && !fetch.StartsWith("ssh") ? "FILE" : fetch.StartsWith("..") || fetch.Contains(":\\") || fetch.StartsWith("/") ? "FILE" : "SSH" };
            row.Provider = fetch.Contains("github.com") ? "github" : fetch.Contains("gitlab") ? "gitlab" : fetch.Contains("codeberg") ? "codeberg" : row.Kind == "FILE" ? "" : "forgejo";
            if (branch.Length > 0) row.Distance = await Git.Distance(root, name + "/" + branch);
            rows.Add(row);
        }
        _remoteList.ItemsSource = rows;
        if (rows.Count == 0) _remoteList.ItemsSource = new[] { new RemoteRow { Name = "", Fetch = Lang.T("Remote ещё нет: соберите адрес в форме ниже и нажмите «прописать в репозиторий».") } };
    }

    Control RemoteView(RemoteRow row)
    {
        if (row.Name.Length == 0) return new TextBlock { Classes = { "note" }, Text = row.Fetch, Margin = new Thickness(10, 8) };
        Control mark = row.Provider.Length > 0 && Icons.Mark(row.Provider, 13) is { } m ? m : Sign("folder-git", "CrumbInk");
        var address = Cell(row.Fetch, quiet: true);
        if (row.Push.Length > 0 && row.Push != row.Fetch) ToolTip.SetTip(address, Lang.F("забирает из: {0}\nотправляет в: {1}", row.Fetch, row.Push));
        var kind = Pill(row.Kind, row.Kind == "SSH" ? "info" : row.Kind == "HTTPS" ? "vi" : "");
        var ab = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5, VerticalAlignment = VerticalAlignment.Center };
        if (row.Distance is { } d)
        {
            ab.Children.Add(Cell("↑" + d.Ahead, d.Ahead > 0 ? "GitStaged" : "CrumbInk"));
            ab.Children.Add(Cell("↓" + d.Behind, d.Behind > 0 ? "GitNew" : "CrumbInk"));
        }
        else ab.Children.Add(Cell("—", quiet: true));
        var fetch = new Button { Classes = { "tool" }, Content = Sign("cloud-download") };
        // An operation of the canon like every Git button: the window names no Git command of its own.
        ToolTip.SetTip(fetch, Canon.Get("fetch_remote").Tip(Canon.Show(Canon.Get("fetch_remote").Argv(new() { ["remote"] = row.Name }))));
        fetch.Click += (_, _) => RunCanon("fetch_remote", new() { ["remote"] = row.Name });
        _starters.Add(fetch);
        var grid = Cells("26,110,*,64,80,Auto", mark, Cell(row.Name, bold: true), address, kind, ab, fetch);
        grid.MinHeight = 30;
        return grid;
    }

    // ------------------------------------------------------------ a new remote

    Control BuildRemoteForm()
    {
        _platformRow = new StackPanel { Orientation = Orientation.Horizontal };
        _typeRow2 = new StackPanel { Orientation = Orientation.Horizontal };
        _remoteName = Field("имя remote", "origin", 100, "Имя remote в репозитории: origin - главный; github, forgejo - зеркала.", "remote_name");
        _owner = Field("владелец или группа", "", 180, "Владелец репозитория на сервере: ваш логин или группа.", "remote_owner");
        _repoName = Field("репозиторий", _project is null ? "" : System.IO.Path.GetFileName(_project.Source.TrimEnd('\\', '/')), double.NaN, "Имя репозитория на сервере; .git в конце не нужен.", "remote_repo");
        _server = Field("сервер: git.example.org", "", double.NaN, "Адрес своего сервера Forgejo или Gitea: имя или https://имя.", "remote_server");
        _sshPort = Field("22", "22", 60, "Порт SSH сервера: обычно 22, у своих серверов бывает другой.", "remote_port");
        foreach (var box in new[] { _remoteName, _owner, _repoName, _server, _sshPort }) box.TextChanged += (_, _) => _ = BuildUrl();
        _builtUrl = new TextBlock { Classes = { "mono" }, TextWrapping = TextWrapping.Wrap }.Ink(TextBlock.ForegroundProperty, "LogExplain");
        MarkPlatforms();
        var names = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,6,Auto,6,*") };
        names.Children.Add(_remoteName);
        Grid.SetColumn(_owner, 2); names.Children.Add(_owner);
        Grid.SetColumn(_repoName, 4); names.Children.Add(_repoName);
        var server = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,6,*,6,Auto") };
        server.Children.Add(_typeRow2);
        Grid.SetColumn(_server, 2); server.Children.Add(_server);
        Grid.SetColumn(_sshPort, 4); server.Children.Add(_sshPort);
        var save = Op("сохранить в remotes.json", () => _ = SaveRemote(), "Записать этот remote в config\\remotes.json программы - список, из которого его можно прописать в любой репозиторий. Адрес с паролем или токеном не сохраняется.", "local", sm: true, id: "remote_save");
        var apply = Op("прописать в репозиторий", ApplyRemote, Canon.Get("remote_add").Tip(), "local", sm: true, id: "remote_apply");
        var pushUrl = Op("origin → ещё push-адрес", AddPushUrl, Canon.Get("origin_push_url").Tip(), "local", sm: true, id: "remote_push_url");
        var actions = new WrapPanel { Children = { save, apply, pushUrl } };
        foreach (var b in actions.Children) b.Margin = new Thickness(0, 0, 6, 6);
        var body = new StackPanel { Spacing = 8, Children =
        {
            _platformRow, server, names,
            new Border { Classes = { "preview" }, Child = _builtUrl },
            actions,
        } };
        _ = BuildUrl();
        return Block("НОВЫЙ REMOTE", "Quasar", body);
    }

    static readonly (string Id, string Mark, string Name)[] Platforms =
    {
        ("github", "github", "GitHub"), ("gitlab", "gitlab", "GitLab"), ("codeberg", "codeberg", "Codeberg"),
        ("forgejo", "forgejo", "Forgejo"), ("gitea", "gitea", "Gitea"), ("custom", "", "свой сервер"),
    };

    void MarkPlatforms()
    {
        if (_platformRow is null || _typeRow2 is null) return;
        _platformRow.Children.Clear();
        foreach (var (id, mark, name) in Platforms)
        {
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 5 };
            if (mark.Length > 0 && Icons.Mark(mark, 11) is { } m) face.Children.Add(m);
            face.Children.Add(new TextBlock { Text = Lang.T(name), VerticalAlignment = VerticalAlignment.Center });
            var chip = new ToggleButton { Classes = { "switch", "chip" }, Content = face, IsChecked = _platform == id };
            chip.Click += (_, _) => { _platform = id; MarkPlatforms(); _ = BuildUrl(); };
            _platformRow.Children.Add(chip);
        }
        _typeRow2.Children.Clear();
        foreach (var type in new[] { "ssh", "https" })
            _typeRow2.Children.Add(Chip(type.ToUpperInvariant(), _urlType == type, () => { _urlType = type; MarkPlatforms(); _ = BuildUrl(); },
                type == "ssh" ? "SSH: вход по ключу (ssh-agent), без паролей в адресе." : "HTTPS: вход через Git Credential Manager или gh / glab."));
        bool own = _platform is "forgejo" or "gitea" or "custom";
        if (_server is not null) _server.IsVisible = own;
        if (_sshPort is not null) _sshPort.IsVisible = own && _urlType == "ssh";
    }

    string _url = "";

    async Task BuildUrl()
    {
        if (_builtUrl is null) return;
        var args = new List<string> { "remote", "url", "--platform", _platform, "--owner", _owner?.Text ?? "", "--repo", _repoName?.Text ?? "", "--type", _urlType };
        if (_platform is "forgejo" or "gitea" or "custom") { args.AddRange(new[] { "--server", _server?.Text ?? "", "--ssh-port", (_sshPort?.Text ?? "22").Trim() }); }
        var answer = await Hub.Ask(args);
        _url = answer.Ok ? answer.Text("url") : "";
        _builtUrl.Text = _url.Length > 0 ? _url : Lang.T("адрес соберётся, когда будут владелец и репозиторий") + (answer.Error.Length > 0 && (_owner?.Text ?? "").Length > 0 ? " · " + answer.Error : "");
    }

    async Task SaveRemote()
    {
        if (_url.Length == 0) { SetStatus("Сначала соберите адрес: владелец и репозиторий."); return; }
        var answer = await Hub.Ask("remote", "save", "--name", (_remoteName?.Text ?? "").Trim(), "--url", _url, "--platform", _platform, "--repo", _repoName?.Text ?? "");
        AppendLines(new[] { "", "› " + answer.Line, answer.Ok ? "[OK] " + Lang.F("сохранено в {0}", answer.Text("config")) : "[ERR] " + answer.Error });
    }

    void ApplyRemote()
    {
        if (_url.Length == 0) { SetStatus("Сначала соберите адрес: владелец и репозиторий."); return; }
        var name = (_remoteName?.Text ?? "").Trim();
        bool exists = _remoteNames.Contains(name);
        RunCanon(exists ? "remote_set_url" : "remote_add", new() { ["remote"] = name, ["url"] = _url });
    }

    void AddPushUrl()
    {
        if (_url.Length == 0) { SetStatus("Сначала соберите адрес: владелец и репозиторий."); return; }
        RunCanon("origin_push_url", new() { ["remote"] = "origin", ["url"] = _url });
    }

    // ------------------------------------------------------------ the access

    void ShowAccess()
    {
        if (_access is null) return;
        _access.Children.Clear();
        var checks = new StackPanel { Spacing = 4 };
        if (_authReport is null) checks.Children.Add(Text("Нажмите «проверить всё»: имя и почта коммитов, вход на GitHub и GitLab, токен Forgejo. Пароли окно не спрашивает и не хранит.", "note"));
        else foreach (var line in AuthLines(_authReport)) checks.Children.Add(line);
        var check = Op("проверить всё", () => RunSteps(HubStep("доступ", new[] { "auth", "--repo", ActiveRoot(true) ?? Paths.Root, "--no-mirrors" },
            "Проверяет Git, имя и почту, gh, glab, вход по SSH на GitHub и GitLab, адреса remote. Пароли не спрашивает.",
            (code, json) => { try { _authReport = JsonNode.Parse(json)?["result"] as JsonObject; } catch { } SummarizeAuth(); ShowAccess(); })), "Auth Doctor: " + Lang.T("проверяет Git, имя и почту, gh, glab, вход по SSH, адреса remote. Пароли не спрашивает."), "net", sm: true, cls: "quiet", id: "auth_check");
        var buttons = new WrapPanel();
        foreach (var b in new Control[]
        {
            OpCanon("config_user", "кто подписывает", () => null, sm: true),
            OpCanon("ssh_github", "ssh -T github", () => null, sm: true),
            OpCanon("ssh_gitlab", "ssh -T gitlab", () => null, sm: true),
            Op("gh auth login", () => OpenTerminal("gh auth login"), "Вход на GitHub через GitHub CLI - во внешнем терминале: там спросят и откроют браузер.", "net", sm: true),
            Op("glab auth login", () => OpenTerminal("glab auth login"), "Вход на GitLab через GitLab CLI - во внешнем терминале.", "net", sm: true),
            Op("Credential Manager", () => { try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("control.exe", "/name Microsoft.CredentialManager") { UseShellExecute = true }); } catch { } }, "Диспетчер учётных данных Windows: где Git хранит токены HTTPS. Здесь их можно удалить.", "read", sm: true),
        }) { b.Margin = new Thickness(0, 0, 6, 6); buttons.Children.Add(b); }
        _access.Children.Add(Block("ДОСТУП", "GitRenamed", new StackPanel { Spacing = 8, Children = { checks, buttons } }, check));
        _access.Children.Add(BuildForgejo());
        var ci = new WrapPanel();
        foreach (var b in new Control[] { OpCanon("gh_runs", "gh run list", () => null, sm: true), OpCanon("gh_watch", "gh run watch", () => null, sm: true), OpCanon("glab_ci", "glab ci status", () => null, sm: true) })
        { b.Margin = new Thickness(0, 0, 6, 6); ci.Children.Add(b); }
        _access.Children.Add(Block("CI", "CrumbInk", ci));
        ApplyBusy();
    }

    IEnumerable<Control> AuthLines(JsonObject report)
    {
        var probes = report["probes"] as JsonArray ?? report["checks"] as JsonArray;
        if (probes is null)
        {
            yield return Text("Отчёт получен - подробности в терминале.", "note");
            yield break;
        }
        foreach (var probe in probes.OfType<JsonObject>())
        {
            bool ok = probe["ok"]?.GetValue<bool>() == true;
            var name = probe["name"]?.ToString() ?? "";
            var said = (probe["stdout"]?.ToString() ?? probe["stderr"]?.ToString() ?? "").Trim().Split('\n').FirstOrDefault() ?? "";
            var row = Cells("18,*,Auto", Sign(ok ? "check" : "circle-alert", ok ? "GitStaged" : "BurnInk"), Cell(name), Pill(said.Length > 40 ? said[..40] + "…" : said, ok ? "ok" : "bad"));
            row.Margin = new Thickness(0);
            ToolTip.SetTip(row, name + "\n" + said);
            yield return row;
        }
    }

    void SummarizeAuth()
    {
        if (_authReport?["probes"] is not JsonArray probes) return;
        foreach (var probe in probes.OfType<JsonObject>())
        {
            bool ok = probe["ok"]?.GetValue<bool>() == true;
            var said = (probe["stdout"]?.ToString() ?? probe["stderr"]?.ToString() ?? "").Trim().Split('\n').FirstOrDefault() ?? "";
            AppendLines(new[] { (ok ? "[OK]   " : "[ERR] ") + probe["name"] + " - " + said });
        }
    }

    TextBox? _forgejoUrl, _forgejoLogin, _forgejoToken;

    Control BuildForgejo()
    {
        _forgejoUrl = Field("сервер Forgejo / Gitea", "", double.NaN, "Адрес сервера: git.example.org или https://git.example.org.", "forgejo_url");
        _forgejoLogin = Field("логин", "", 120, "Ваш логин на сервере.", "forgejo_login");
        _forgejoToken = Field("токен (Settings → Applications)", "", double.NaN, "Личный токен доступа: Settings → Applications → Generate New Token. Окно проверит его на сервере и отдаст хранилищу Git (Credential Manager); в файлы программы и в журнал токен не пишется.", "forgejo_token");
        _forgejoToken.PasswordChar = '•';
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,6,Auto"), RowDefinitions = new RowDefinitions("Auto,6,Auto") };
        grid.Children.Add(_forgejoUrl);
        Grid.SetColumn(_forgejoLogin, 2); grid.Children.Add(_forgejoLogin);
        Grid.SetRow(_forgejoToken, 2); Grid.SetColumnSpan(_forgejoToken, 3); grid.Children.Add(_forgejoToken);
        var buttons = new WrapPanel();
        foreach (var b in new Control[]
        {
            Op("сервер отвечает?", () => Forgejo("check"), "Спрашивает версию сервера: адрес верный и сервер жив.", "net", sm: true),
            Op("сохранить токен", () => Forgejo("sign-in"), "Проверяет токен на сервере (/api/v1/user) и отдаёт его хранилищу Git: дальше git push по HTTPS берёт его сам.", "net", sm: true, cls: "quiet"),
            Op("кто я", () => Forgejo("whoami"), "Под каким аккаунтом токен из хранилища Git.", "net", sm: true),
            Op("мои репозитории", () => Forgejo("repos"), "Список ваших репозиториев на сервере - в терминал.", "net", sm: true),
            Op("забыть токен", () => Forgejo("sign-out"), "Убирает токен из хранилища Git этой машины. На сервере токен остаётся действующим, пока его не отзовут там.", "local", sm: true, cls: "burn"),
        }) { b.Margin = new Thickness(0, 0, 6, 6); buttons.Children.Add(b); }
        return Block("FORGEJO / GITEA", "GitConflict", new StackPanel { Spacing = 8, Children = { grid, buttons } });
    }

    /// <summary>A command of Forgejo through the door; the token, when there is one, goes on its stdin and is cleared from the field.</summary>
    async void Forgejo(string action)
    {
        var url = (_forgejoUrl?.Text ?? "").Trim();
        if (url.Length == 0) { SetStatus("Впишите адрес сервера Forgejo."); return; }
        var args = new List<string> { "forgejo", action, "--url", url };
        if ((_forgejoLogin?.Text ?? "").Trim() is { Length: > 0 } login) { args.Add("--login"); args.Add(login); }
        string? token = null;
        if (action == "sign-in")
        {
            token = (_forgejoToken?.Text ?? "").Trim();
            if (token.Length == 0) { SetStatus("Вставьте токен в поле."); return; }
        }
        AppendLines(new[] { "", $"===== Forgejo: {action} =====", "› " + Hub.Line(args) + (token is null ? "" : "   (" + Lang.T("токен - через stdin, не в строке") + ")") });
        var answer = await Hub.Ask(args, token);
        if (token is not null && _forgejoToken is not null) _forgejoToken.Text = "";
        if (answer.Json is { } json)
        {
            var said = action switch
            {
                "check" => Lang.F("сервер {0} отвечает, версия {1}", json["server"], json["version"]),
                "sign-in" => answer.Ok ? Lang.F("токен проверен и сохранён: {0}", json["login"]) : Lang.F("токен не принят: {0} {1}", json["message"], json["detail"]),
                "whoami" => answer.Ok ? Lang.F("токен принадлежит: {0}", json["data"]?["login"]) : Lang.F("нет токена или он не действует: {0}", json["message"] ?? json["api"]?["error"]),
                "repos" => answer.Ok ? string.Join("\n", (json["data"] as JsonArray ?? new()).OfType<JsonObject>().Select(r => "  " + r["full_name"] + (r["private"]?.GetValue<bool>() == true ? "  (private)" : ""))) : answer.Error,
                _ => answer.Ok ? Lang.T("токен убран из хранилища Git") : answer.Error,
            };
            AppendLines(new[] { (answer.Ok ? "[OK] " : "[ERR] ") + said });
        }
        else AppendLines(new[] { "[ERR] " + answer.Error });
    }
}
