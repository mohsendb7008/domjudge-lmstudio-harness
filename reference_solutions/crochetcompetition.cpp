#include<iostream>
using namespace std;

const int day = 60 * 24;
const int week = day * 7;

int read_time() {
    string name;
    int h, m, t;
    char jnk;
    cin >> name >> h >> jnk >> m;
    t = 60 * h + m;
    if(name[0] == 'M') return t;
    if(name[2] == 'e') return t + day;
    if(name[0] == 'W') return t + day * 2;
    if(name[0] == 'T') return t + day * 3;
    if(name[0] == 'F') return t + day * 4;
    if(name[1] == 'a') return t + day * 5;
    if(name[0] == 'S') return t + day * 6;
    return -1;
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);
    int t1 = read_time(), t2 = read_time();
    if(t1 == t2) {
        cout << "7 days\n";
        return 0;
    }
    int t = (t2 - t1 + week) % week;
    int days = t / day; t %= day;
    int hours = t / 60; t %= 60;
    int nonz = (hours != 0) + (days != 0) + (t != 0);
    bool andprnt = false;
    if(days != 0) {
        cout << days << " day";
        if(days > 1) cout << 's';
        if(nonz == 3) cout << ", ";
        else if(nonz == 2) cout << " and ", andprnt = true;
    }
    if(hours != 0) {
        cout << hours << " hour";
        if(hours > 1) cout << 's';
        if(nonz == 3) cout << ", ";
        else if(nonz == 2 && !andprnt)
            cout << " and ";
    }
    if(t != 0) {
        cout << t << " minute";
        if(t > 1) cout << 's';
    }
    cout << '\n';
}

