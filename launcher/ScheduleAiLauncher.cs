using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;

public static class ScheduleAiLauncher
{
    private const string Url = "http://127.0.0.1:4173/";

    public static int Main()
    {
        var root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var script = Path.Combine(root, "scripts", "start-local.ps1");

        if (!File.Exists(script))
        {
            Message("找不到启动脚本：\n" + script + "\n\n请把 ScheduleAI.exe 放在项目根目录 G:\\施工计划 下运行。");
            return 1;
        }

        if (!IsHealthy())
        {
            StartServer(root, script);
            WaitForServer();
        }

        OpenBrowser(Url);
        return 0;
    }

    private static void StartServer(string root, string script)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoExit -ExecutionPolicy Bypass -File \"" + script + "\" -Build",
            WorkingDirectory = root,
            UseShellExecute = true,
            WindowStyle = ProcessWindowStyle.Normal
        };
        Process.Start(psi);
    }

    private static void WaitForServer()
    {
        for (var i = 0; i < 40; i++)
        {
            if (IsHealthy()) return;
            Thread.Sleep(500);
        }
    }

    private static bool IsHealthy()
    {
        try
        {
            var request = (HttpWebRequest)WebRequest.Create(Url + "api/health");
            request.Timeout = 800;
            using (var response = (HttpWebResponse)request.GetResponse())
            {
                return response.StatusCode == HttpStatusCode.OK;
            }
        }
        catch
        {
            return false;
        }
    }

    private static void OpenBrowser(string url)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = url,
            UseShellExecute = true
        });
    }

    private static void Message(string text)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = "-NoExit -Command \"Write-Host '" + text.Replace("'", "''").Replace("\r", "").Replace("\n", "`n") + "'\"",
            UseShellExecute = true
        });
    }
}
